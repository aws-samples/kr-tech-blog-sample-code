import React, { useState, useCallback, useEffect, useMemo } from "react";
import {
  AppLayout,
  BreadcrumbGroup,
  Header,
  SpaceBetween,
  Box,
  Badge,
  Button,
  Flashbar,
  ProgressBar,
} from "@cloudscape-design/components";
import { TokenAuthProvider, useTokenAuth } from "./auth/TokenProvider";
import { loadConfig } from "./config";
import { PipelineMap } from "./components/PipelineMap";
import { ModuleDetailPanel } from "./components/ModuleDetailPanel";
import { PIPELINE_MODULES, type ModuleConfig, type ModuleStatus } from "./data/pipeline-config";

// B2: how often the dashboard re-fetches live module progress so a module
// completing in the notebook flips its node without a manual refresh.
const POLL_MS = 20_000;

// Normalize the backend's stored form ("in_progress") to the frontend enum
// ("in-progress"). Returns null for anything unrecognized (ignored -> static).
function normalizeStatus(raw: string): ModuleStatus | null {
  switch (raw) {
    case "completed":
      return "completed";
    case "in_progress":
    case "in-progress":
      return "in-progress";
    case "locked":
      return "locked";
    default:
      return null;
  }
}

function Dashboard(): React.JSX.Element {
  const { userId, isAuthenticated, apiClient } = useTokenAuth();
  const [selectedModule, setSelectedModule] = useState<ModuleConfig | null>(null);
  const [openingWorkspace, setOpeningWorkspace] = useState(false);
  const [workspaceError, setWorkspaceError] = useState<string | null>(null);
  // B3: the participant's display name, fetched from app-status. Falls back to
  // the userId slug when the row predates stored names.
  const [displayName, setDisplayName] = useState<string | null>(null);
  // B2: live per-module status from the DDB session row (canonical long ids).
  const [liveProgress, setLiveProgress] = useState<Record<string, ModuleStatus>>({});
  // SageMaker app lifecycle for THIS participant's one JupyterLab space:
  // "InService" | "Pending" | "Deleting" | "Deleted" | "Failed" | "NotFound", or null
  // before the first poll returns. The poll below already fetched this and threw it away,
  // which is why "Open Workspace" used to be offered when there was nothing to open.
  const [workspaceStatus, setWorkspaceStatus] = useState<string | null>(null);
  // The space's real provisioned volume in GB, from the same poll. null = not known yet or
  // unreadable; the panel falls back to the module's recommendation only in that case.
  const [workspaceStorageGB, setWorkspaceStorageGB] = useState<number | null>(null);
  // Counter, not a boolean. Each "start my workspace" request bumps it, and the panel's
  // React key includes it, so EVERY request remounts the panel and its
  // useState(openInstanceOptionsOnMount) actually re-runs.
  //
  // A boolean here was a silent dead end: the participant clicks Start Workspace (flag
  // true, modal opens), clicks the modal's Cancel — which only clears the modal's own local
  // showInstanceOptions, never this flag — and clicks Start Workspace again. The flag was
  // already true, so the key was unchanged, so React reused the mounted panel and the modal
  // never reopened. The primary call to action became a no-op.
  const [startRequest, setStartRequest] = useState(0);
  // Which start request the panel should honour by opening Instance Options on mount. Null
  // when the panel was opened by clicking a module node (configure, not start).
  const [startRequestHonoured, setStartRequestHonoured] = useState<number | null>(null);

  // Fetch identity + live module progress on mount, then poll (and on window
  // focus) so a module completing in the notebook flips its node without a
  // manual refresh. Non-fatal: on any error we keep the last-known/static view.
  useEffect(() => {
    if (!userId || !apiClient) return;
    let active = true;

    const refresh = async () => {
      try {
        const s = await apiClient.getAppStatus(userId);
        if (!active) return;
        setDisplayName(s.name || userId);
        // "Unknown", never null: null is the "not asked yet" sentinel that disables the
        // header button. app_status does `status = resp.get("Status")`, which serialises to
        // JSON null if describe_app omits it, so an ANSWERED call could otherwise lock the
        // button to a disabled "Checking workspace…" forever.
        setWorkspaceStatus(s.status ?? "Unknown");
        setWorkspaceStorageGB(typeof s.storageGB === "number" ? s.storageGB : null);
        const merged: Record<string, ModuleStatus> = {};
        for (const [id, raw] of Object.entries(s.moduleProgress ?? {})) {
          const norm = normalizeStatus(String(raw));
          if (norm) merged[id] = norm;
        }
        setLiveProgress(merged);
      } catch {
        if (!active) return;
        setDisplayName((prev) => prev ?? userId);
        // Do NOT leave workspaceStatus at null on a failed poll. null means "not asked
        // yet" and DISABLES the header button, so a participant whose app-status call keeps
        // failing would sit on a permanently disabled "Checking workspace…" — a dead end
        // this change would otherwise have introduced. "Unknown" keeps the button usable:
        // it offers Start Workspace, which opens Instance Options, and that is safe either
        // way (a same-type Apply against an already-running app is the 409 the panel
        // already absorbs as a no-op).
        setWorkspaceStatus((prev) => prev ?? "Unknown");
      }
    };

    void refresh();
    const timer = window.setInterval(() => void refresh(), POLL_MS);
    const onFocus = () => void refresh();
    window.addEventListener("focus", onFocus);
    return () => {
      active = false;
      window.clearInterval(timer);
      window.removeEventListener("focus", onFocus);
    };
  }, [userId, apiClient]);

  // Merge live progress over each module's static default; derive counts from it.
  const mergedModules = useMemo(
    () => PIPELINE_MODULES.map((m) => ({ ...m, status: liveProgress[m.id] ?? m.status })),
    [liveProgress]
  );
  const completedCount = mergedModules.filter((m) => m.status === "completed").length;
  const inProgressCount = mergedModules.filter((m) => m.status === "in-progress").length;
  const totalCount = mergedModules.length;
  const progressPercent = Math.round((completedCount / totalCount) * 100);

  const handleModuleSelect = useCallback((module: ModuleConfig) => {
    setSelectedModule(module);
    setStartRequestHonoured(null);
  }, []);

  // Is there a workspace to open? "Pending" deliberately counts as NOT openable: the app
  // exists but no server is listening yet, so a deep link lands on a route nothing answers.
  const workspaceRunning = workspaceStatus === "InService";
  const workspaceStarting = workspaceStatus === "Pending";
  // Deleting is NOT starting — it is the idle timer or a restart tearing the app down, and
  // labelling it "Workspace starting…" told the participant to wait for something that was
  // never going to happen. Own label, still disabled until teardown finishes.
  const workspaceStopping = workspaceStatus === "Deleting";

  // The module whose Instance Options to open when the participant asks to start a stopped
  // workspace: the one they are on, else the first unfinished one, else M1. The instance is
  // workspace-wide (one JupyterLab space serves every module), so any module's panel sets
  // the same thing — this just picks the least surprising one.
  // COST-CRITICAL. This must not resolve to a GPU module for a participant who has not
  // asked for one.
  //
  // create_user seeds the DDB row with moduleProgress: {} (create_user/handler.py), so on
  // day one liveProgress is EMPTY and mergedModules falls back to the static seeds in
  // pipeline-config.ts — where m02-cosmos-reason is seeded "in-progress" purely so the map
  // looks alive in a screenshot. "First in-progress module" therefore resolved to m02, whose
  // recommendedInstance is ml.g5.12xlarge: $8.718/hr in ap-northeast-2. One click on the
  // header button would have opened Apply & Restart preselected on that, for someone who
  // had run nothing. The old dead-end behaviour at least cost $0.
  //
  // So: trust the seeds only when the backend has actually reported progress. With no real
  // progress, start from the first module (M1, ml.t3.medium).
  const hasRealProgress = Object.keys(liveProgress).length > 0;
  const startFromModule = useMemo(
    () =>
      (hasRealProgress
        ? mergedModules.find((m) => m.status === "in-progress") ??
          mergedModules.find((m) => m.status !== "completed")
        : undefined) ?? mergedModules[0],
    [mergedModules, hasRealProgress]
  );

  const handleStartWorkspace = useCallback(() => {
    setSelectedModule(startFromModule);
    setStartRequest((n) => {
      const next = n + 1;
      setStartRequestHonoured(next);
      return next;
    });
  }, [startFromModule]);

  const handleClosePanel = useCallback(() => {
    setSelectedModule(null);
  }, []);

  // Open the JupyterLab workspace via a FRESH presigned URL generated at click
  // time — avoids the 5-minute redeem-window problem entirely. One JupyterLab
  // space serves all modules, so this is not module-specific.
  const handleOpenWorkspace = useCallback(async () => {
    if (!userId || !apiClient) return;
    setOpeningWorkspace(true);
    setWorkspaceError(null);
    try {
      // Re-check RIGHT NOW instead of trusting a snapshot up to POLL_MS (20s) old. In that
      // window the app can vanish two ordinary ways — the idle timer deletes it, or the
      // participant just hit Apply & Restart, whose first step is deleting the app — and
      // opening a presigned URL with no app lands them on exactly the Studio page this
      // change exists to keep them away from.
      const live = await apiClient.getAppStatus(userId);
      setWorkspaceStatus(live.status ?? "Unknown");
      if (live.status !== "InService") {
        setWorkspaceError(
          "Your workspace is not running right now, so there is nothing to open. " +
            "Use Start Workspace to bring it up."
        );
        return;
      }
      const { presignedUrl } = await apiClient.getWorkspaceUrl(userId);
      window.open(presignedUrl, "_blank", "noopener,noreferrer");
    } catch (e) {
      setWorkspaceError(
        e instanceof Error ? e.message : "Failed to open workspace. Try again."
      );
    } finally {
      setOpeningWorkspace(false);
    }
  }, [userId, apiClient]);

  // The detail panel's "Re-run Lab" / "Resume Lab" button. moduleId is unused because a
  // single JupyterLab space serves every module.
  //
  // It had the SAME dead end as the header button: it opened a presigned URL
  // unconditionally, so with no app running the participant landed on the Studio home page
  // with nothing they were allowed to click. Route to the workspace only when there is one;
  // otherwise open Instance Options, which is where Apply & Restart starts it.
  const handleStartLab = useCallback(
    (moduleId: string) => {
      if (workspaceRunning) {
        void handleOpenWorkspace();
        return;
      }
      const target = mergedModules.find((m) => m.id === moduleId);
      if (target) setSelectedModule(target);
      setStartRequest((n) => {
        const next = n + 1;
        setStartRequestHonoured(next);
        return next;
      });
    },
    [workspaceRunning, handleOpenWorkspace, mergedModules]
  );

  return (
    <>
      <AppLayout
        navigationHide
        toolsHide
        breadcrumbs={
          <BreadcrumbGroup
            items={[
              { text: "AV 3.0 Blueprint Lab", href: "/" },
              { text: "Pipeline Map", href: "#" },
            ]}
          />
        }
        content={
          <SpaceBetween size="l">
            {/* Header */}
            <Header
              variant="h1"
              description={
                (displayName ? `${displayName} — ` : "") +
                "Autonomous Vehicle Perception Pipeline — complete each module sequentially to build your AV perception stack."
              }
              actions={
                <SpaceBetween direction="horizontal" size="s">
                  <Badge color="green">{completedCount} Completed</Badge>
                  <Badge color="blue">{inProgressCount} In Progress</Badge>
                  <Badge color="grey">
                    {totalCount - completedCount - inProgressCount} Locked
                  </Badge>
                  {/* One button, three truths. It used to always say "Open Workspace"
                      and always be enabled, so a participant who had not started an
                      instance yet was sent to the SageMaker Studio home page — where the
                      only visible action ("Run space") is one a participant is not
                      permitted to perform. Now the label follows the live app status. */}
                  {workspaceRunning ? (
                    <Button
                      variant="primary"
                      iconName="external"
                      loading={openingWorkspace}
                      disabled={!isAuthenticated || openingWorkspace}
                      onClick={() => void handleOpenWorkspace()}
                    >
                      Open Workspace
                    </Button>
                  ) : workspaceStarting ? (
                    <Button variant="primary" loading disabled>
                      Workspace starting…
                    </Button>
                  ) : workspaceStopping ? (
                    <Button variant="primary" loading disabled>
                      Shutting down…
                    </Button>
                  ) : (
                    <Button
                      variant="primary"
                      iconName="caret-right-filled"
                      disabled={!isAuthenticated || workspaceStatus === null}
                      onClick={handleStartWorkspace}
                    >
                      {/* Demo mode never starts the poll (no userId/token), so
                          "Checking workspace…" would describe a request never made. */}
                      {isAuthenticated && workspaceStatus === null
                        ? "Checking workspace…"
                        : "Start Workspace"}
                    </Button>
                  )}
                </SpaceBetween>
              }
            >
              Pipeline Map
            </Header>

            {/* Workspace open error */}
            {workspaceError && (
              <Box padding={{ horizontal: "l" }}>
                <Flashbar
                  items={[
                    {
                      type: "error",
                      dismissible: true,
                      onDismiss: () => setWorkspaceError(null),
                      content: workspaceError,
                    },
                  ]}
                />
              </Box>
            )}

            {/* Progress Bar */}
            <Box padding={{ horizontal: "l" }}>
              <ProgressBar
                value={progressPercent}
                additionalInfo={`${completedCount} of ${totalCount} modules completed`}
                label="Overall Progress"
                variant="standalone"
              />
            </Box>

            {/* Auth Warning */}
            {!isAuthenticated && (
              <Box
                padding="m"
                margin={{ horizontal: "l" }}
                color="text-status-warning"
                fontSize="body-s"
              >
                <strong>Demo Mode</strong> — Add{" "}
                <code>?userId=YOUR_ID&amp;token=YOUR_TOKEN</code> to the URL to connect to
                your lab environment.
              </Box>
            )}

            {/* Pipeline Visualization */}
            <Box padding={{ horizontal: "l" }}>
              <div
                style={{
                  backgroundColor: "#fafafa",
                  border: "1px solid #e9ebed",
                  borderRadius: "12px",
                  padding: "20px",
                }}
              >
                <PipelineMap
                  modules={mergedModules}
                  onModuleSelect={handleModuleSelect}
                  selectedModuleId={selectedModule?.id ?? null}
                />
              </div>
            </Box>

            {/* Legend */}
            <Box padding={{ horizontal: "l", bottom: "l" }}>
              <SpaceBetween direction="horizontal" size="l">
                <LegendItem color="#037f0c" label="Completed" />
                <LegendItem color="#d97706" label="In Progress" />
                <LegendItem color="#5f6b7a" label="Locked" />
                <span
                  style={{
                    display: "flex",
                    alignItems: "center",
                    gap: "6px",
                    fontSize: "13px",
                    color: "#5f6b7a",
                  }}
                >
                  <svg width="24" height="10">
                    <line
                      x1="0"
                      y1="5"
                      x2="18"
                      y2="5"
                      stroke="#adb5bd"
                      strokeWidth="2"
                      strokeDasharray="3,3"
                    />
                  </svg>
                  Locked path
                </span>
                <span
                  style={{
                    display: "flex",
                    alignItems: "center",
                    gap: "6px",
                    fontSize: "13px",
                    color: "#5f6b7a",
                  }}
                >
                  <svg width="24" height="10">
                    <line x1="0" y1="5" x2="16" y2="5" stroke="#adb5bd" strokeWidth="2" />
                    <polygon points="16,2 22,5 16,8" fill="#adb5bd" />
                  </svg>
                  Data flow
                </span>
              </SpaceBetween>
            </Box>
          </SpaceBetween>
        }
      />

      {/* Detail Panel Overlay */}
      {selectedModule && (
        <ModuleDetailPanel
          // Remount on every module change AND every start request. The nonce is what makes
          // a repeat click work: a boolean would leave the key unchanged after the modal was
          // cancelled, React would reuse the mounted panel, and the button would do nothing.
          key={`${selectedModule.id}-${startRequest}`}
          openInstanceOptionsOnMount={startRequestHonoured === startRequest}
          liveStorageGB={workspaceStorageGB}
          module={selectedModule}
          onClose={handleClosePanel}
          onStartLab={handleStartLab}
        />
      )}
    </>
  );
}

function LegendItem({ color, label }: { color: string; label: string }): React.JSX.Element {
  return (
    <span style={{ display: "flex", alignItems: "center", gap: "6px", fontSize: "13px" }}>
      <span
        style={{
          width: "12px",
          height: "12px",
          borderRadius: "50%",
          backgroundColor: color,
          display: "inline-block",
        }}
      />
      {label}
    </span>
  );
}

export function App(): React.JSX.Element {
  const [configLoaded, setConfigLoaded] = useState(false);
  const [configError, setConfigError] = useState<string | null>(null);

  useEffect(() => {
    loadConfig()
      .then(() => setConfigLoaded(true))
      .catch((err: Error) => setConfigError(err.message));
  }, []);

  if (configError) {
    return (
      <div style={{ padding: "40px", textAlign: "center", color: "#d91515" }}>
        <h2>Configuration Error</h2>
        <p>{configError}</p>
        <p>Ensure /config.json is available.</p>
      </div>
    );
  }

  if (!configLoaded) {
    return <div style={{ padding: "40px", textAlign: "center" }}>Initializing...</div>;
  }

  return (
    <TokenAuthProvider>
      <Dashboard />
    </TokenAuthProvider>
  );
}

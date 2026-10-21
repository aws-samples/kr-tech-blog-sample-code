import React, { useState, useEffect, useRef, useCallback } from "react";
import {
  Box,
  Button,
  ColumnLayout,
  ExpandableSection,
  Flashbar,
  Header,
  Modal,
  RadioGroup,
  SpaceBetween,
  type RadioGroupProps,
  type FlashbarProps,
} from "@cloudscape-design/components";
import { type ModuleConfig } from "../data/pipeline-config";
import { useTokenAuth } from "../auth/TokenProvider";
import { ApiError, type AppStatusResponse } from "../api/client";

interface InstanceOptionsPanelProps {
  // The space's REAL provisioned volume in GB, or null when unknown. Everything about
  // storage in this panel is computed from this — module.storageGB is only a recommendation.
  liveStorageGB?: number | null;
  module: ModuleConfig;
  onClose: () => void;
}

export function InstanceOptionsPanel({
  liveStorageGB = null,
  module,
  onClose,
}: InstanceOptionsPanelProps): React.JSX.Element {
  const { userId, apiClient } = useTokenAuth();
  const [selectedInstance, setSelectedInstance] = useState(module.recommendedInstance);
  // Baseline = the volume that actually exists. Falling back to module.storageGB only while
  // the live value is unknown keeps the panel from showing a blank, but it is a fallback,
  // not the source of truth: sizing against it is exactly the bug this replaces — the panel
  // showed "100 GB" for a 5 GB space, and +50 GB then sent a delta computed from 100 while
  // the backend added it to 5.
  const storageBaseline = liveStorageGB ?? module.storageGB;
  const [storageGB, setStorageGB] = useState(storageBaseline);
  const [applying, setApplying] = useState(false);
  const [applyError, setApplyError] = useState<string | null>(null);
  // Live app status after Apply — polled from the backend so the participant
  // sees Pending/InService/Failed instead of a static label. null = not polling.
  const [appStatus, setAppStatus] = useState<AppStatusResponse | null>(null);
  const [polling, setPolling] = useState(false);
  const pollTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  // Cancel flag for the CURRENTLY RUNNING poll loop. pollAppStatus used to return a
  // cleanup closure that nobody ever called, so a tick already in flight re-armed the
  // timer after the unmount cleanup had run, and a second Apply stacked a second loop
  // over the one timer ref — orphaning the first forever. Holding the flag in a ref lets
  // both the unmount effect and the next Apply actually stop the previous loop.
  const pollCancelled = useRef<{ v: boolean } | null>(null);
  // How long to keep polling before giving up. A failed start can leave the app absent
  // indefinitely (create_app raised, nothing to describe), and an unbounded poll left the
  // panel on "Waiting for the workspace to be created…" with Apply disabled forever.
  const POLL_DEADLINE_MS = 10 * 60 * 1000;

  // Poll getAppStatus until the app reaches a terminal state, or the deadline passes.
  const pollAppStatus = useCallback(
    // dispatched=true when changeInstance returned 2xx, i.e. a real delete->recreate cycle
    // is now running server-side. false when it returned 409 ("already set"), i.e. nothing
    // was dispatched and whatever we read first IS the answer.
    (dispatched: boolean) => {
      if (!userId || !apiClient) return;
      // Stop any previous loop before starting a new one.
      if (pollCancelled.current) pollCancelled.current.v = true;
      if (pollTimer.current) clearTimeout(pollTimer.current);
      const me = { v: false };
      pollCancelled.current = me;

      const startedAt = Date.now();
      // When a cycle was dispatched, the app we want does not exist yet: the old one is
      // being deleted and the new one has not been created. So the FIRST terminal status
      // we see can only be the previous cycle's leftovers. Require one non-terminal
      // observation (Deleting / NotFound / Pending) before believing any terminal one.
      //
      // The old guard compared instanceType against selectedInstance instead, which cannot
      // work for a same-type restart — the case the relaxed 409 in change_instance now
      // makes reachable — because there the stale app's type IS the requested type, so a
      // just-Failed app from the previous attempt was reported as this attempt's result
      // within one second.
      let sawNonTerminal = !dispatched;

      const tick = async () => {
        try {
          const s = await apiClient.getAppStatus(userId);
          if (me.v) return;
          const terminal = s.status === "InService" || s.status === "Failed";
          if (!terminal) {
            sawNonTerminal = true;
            setAppStatus(s);
          } else if (sawNonTerminal) {
            setAppStatus(s);
            setPolling(false);
            return;
          }
          // A recorded failure is terminal even though the app is absent: create_app threw,
          // so there will never be an app to describe. The backend already explains why in
          // lastInstanceChangeError; without this the poll ran to the deadline showing a
          // reassuring "waiting" message over a known failure.
          const err = s.lastInstanceChangeError;
          if (err && err.requestedType === selectedInstance && sawNonTerminal) {
            setAppStatus(s);
            setPolling(false);
            return;
          }
        } catch {
          // Transient (e.g. API GW hiccup) — keep polling; don't surface noise.
        }
        if (me.v) return;
        if (Date.now() - startedAt > POLL_DEADLINE_MS) {
          setPolling(false);
          setApplyError(
            "The workspace did not come up within 10 minutes. Re-open Instance Options " +
              "to try again, pick a different instance type, or ask the workshop admin to " +
              "check the session."
          );
          return;
        }
        pollTimer.current = setTimeout(() => void tick(), 8000);
      };

      setPolling(true);
      void tick();
    },
    [userId, apiClient, selectedInstance]
  );

  useEffect(() => {
    return () => {
      if (pollCancelled.current) pollCancelled.current.v = true;
      if (pollTimer.current) clearTimeout(pollTimer.current);
    };
  }, []);

  const instanceOptions: RadioGroupProps.RadioButtonDefinition[] = [
    {
      value: module.recommendedInstance,
      label: module.recommendedInstance,
      description: "Recommended — optimized for this module",
    },
    ...module.alternatives.map((alt) => ({
      value: alt,
      label: alt,
      description: getInstanceDescription(alt),
    })),
  ];

  // Storage the user has chosen to add on top of the module default.
  const storageAdded = storageGB - storageBaseline;

  // module.errorHints is a STATIC per-module troubleshooting reference keyed by exception
  // name ("CalledProcessError", "EmptyManifest", ...). Every module has at least one, so
  // rendering it as a warning Flashbar made an alarm that fired on EVERY open — and the one
  // it showed was Object.keys(...)[0], an arbitrary entry unrelated to anything that had
  // happened. A banner that is always on is a banner nobody reads, which is precisely the
  // failure mode that let a real hf-cache warning scroll past unnoticed for 20 minutes.
  //
  // So it is reference material now, not an alert: listed in full, labelled by exception
  // name, collapsed by default. Warning Flashbars are reserved for LIVE conditions — see
  // changeError (lastInstanceChangeError) further down, which is a real one.
  const errorHintEntries = Object.entries(module.errorHints);

  function handleInstanceChange(detail: RadioGroupProps.ChangeDetail): void {
    setSelectedInstance(detail.value);
  }

  function handleAddStorage(amount: number): void {
    setStorageGB((prev) => prev + amount);
  }

  function handleRevert(): void {
    setSelectedInstance(module.recommendedInstance);
    setStorageGB(storageBaseline);
  }

  async function handleApply(): Promise<void> {
    if (!userId || !apiClient) {
      setApplyError(
        "Not authenticated. Open this dashboard via the participant link " +
          "(?userId=...&token=...)."
      );
      return;
    }
    setApplying(true);
    setApplyError(null);
    setAppStatus(null);
    try {
      // Always apply the selected instance. We do NOT assume the workspace is
      // already on the recommended instance — a freshly-provisioned user starts
      // on ml.t3.medium (CPU), so selecting the recommended GPU instance and
      // clicking Apply must actually switch it. The backend returns 409 when the
      // workspace is already on the requested type; treat that as a no-op.
      //
      // The change can take minutes (delete app -> resize -> recreate), which can
      // exceed the API Gateway 29s timeout and surface as a 502/504 even though
      // the change is proceeding server-side. So a gateway timeout is NOT fatal:
      // we fall through to polling getAppStatus, which reflects the real outcome.
      // Did change_instance actually dispatch a delete->recreate cycle? 409 means it did
      // not (the app is already running the requested type), and the poller needs to know:
      // with no cycle running, the first status it reads IS the answer.
      let dispatched = true;
      try {
        await apiClient.changeInstance(userId, selectedInstance);
      } catch (e) {
        const isAlreadySet = e instanceof ApiError && e.status === 409;
        const isGatewayTimeout =
          e instanceof ApiError && (e.status === 502 || e.status === 504);
        if (!isAlreadySet && !isGatewayTimeout) {
          throw e;
        }
        if (isAlreadySet) dispatched = false;
      }
      // Storage resize. expand_storage runs its OWN delete -> update_space -> create_app
      // cycle, so firing it while change_instance's cycle is in flight puts two tails on
      // one space: they both wait for the delete, both update_space, and one loses
      // create_app with ResourceInUse. expand_storage has no recovery path and
      // retry_attempts=0, so the resize is then dropped with nothing recorded anywhere.
      //
      // Only one cycle per click: when change_instance dispatched, it already recreates the
      // app, so the resize has to be a separate, later action. When it returned 409 there
      // is no cycle in flight and expand_storage is safe to run now.
      if (storageAdded > 0 && !dispatched) {
        try {
          await apiClient.expandStorage(userId, storageAdded);
        } catch (e) {
          // Same gateway-timeout tolerance for the storage resize.
          if (!(e instanceof ApiError && (e.status === 502 || e.status === 504))) {
            throw e;
          }
        }
      } else if (storageAdded > 0) {
        setApplyError(
          `Applying ${selectedInstance} now. Storage was NOT resized — re-open Instance ` +
            `Options once the workspace is running and add the ${storageAdded} GB then ` +
            `(a resize and an instance change cannot run at the same time).`
        );
      }
      // Do not close — start polling so the user watches the workspace come up
      // (and sees a capacity failure with an actionable hint if it happens).
      pollAppStatus(dispatched);
    } catch (e) {
      setApplyError(
        e instanceof Error ? e.message : "Failed to apply changes. Try again."
      );
    } finally {
      setApplying(false);
    }
  }

  // Keep in sync with _GPU_INSTANCE_PREFIXES in infra/lambda/shared/config.py.
  // g7e must be listed separately from g6/g5 — it is its own family, and an
  // unmatched GPU instance here shows the CPU-instance copy to the participant.
  const isGpuInstance = /^ml\.(g4dn|g5|g6|g7e|p3|p4d|p5)\./.test(selectedInstance);
  const canRevert =
    selectedInstance !== module.recommendedInstance || storageAdded !== 0;

  return (
    <Modal
      visible
      onDismiss={onClose}
      header={<Header variant="h2">Instance Options — {module.title}</Header>}
      size="medium"
      footer={
        <Box float="right">
          <SpaceBetween direction="horizontal" size="xs">
            <Button
              variant="link"
              onClick={handleRevert}
              disabled={!canRevert || applying || polling}
            >
              Revert to Default
            </Button>
            <Button variant="normal" onClick={onClose} disabled={applying}>
              {polling || appStatus ? "Close" : "Cancel"}
            </Button>
            <Button
              variant="primary"
              onClick={() => void handleApply()}
              disabled={applying || polling}
              loading={applying}
            >
              Apply &amp; Restart
            </Button>
          </SpaceBetween>
        </Box>
      }
    >
      <SpaceBetween size="l">
        {/* Apply error */}
        {applyError && (
          <Flashbar
            items={[
              {
                type: "error",
                content: applyError,
                dismissible: true,
                onDismiss: () => setApplyError(null),
                id: "apply-error",
              },
            ]}
          />
        )}

        {/* Live app status after Apply (Pending / InService / Failed+capacity) */}
        {(polling || appStatus) && (
          <Flashbar items={[buildStatusFlash(appStatus, polling)]} />
        )}

        {/* Restart notice — applying an instance change always recreates the app */}
        <Flashbar
          items={[
            {
              type: "info",
              header: "Applying restarts your workspace",
              content:
                `“Apply & Restart” switches your workspace to ${selectedInstance}` +
                (isGpuInstance
                  ? " and loads the GPU software image automatically."
                  : ".") +
                " This recreates JupyterLab (a few minutes). When it finishes, " +
                "click “Open Workspace” again to get a fresh link.",
              dismissible: false,
              id: "restart-notice",
            },
          ]}
        />

        {/* Troubleshooting reference — collapsed, not an alert. See errorHintEntries. */}
        {errorHintEntries.length > 0 && (
          <ExpandableSection
            headerText={`Troubleshooting ${module.id.toUpperCase()} (${errorHintEntries.length})`}
            variant="footer"
          >
            <SpaceBetween size="s">
              {errorHintEntries.map(([name, hint]) => (
                <Box key={name}>
                  <Box variant="awsui-key-label">{name}</Box>
                  <Box variant="p">{hint}</Box>
                </Box>
              ))}
            </SpaceBetween>
          </ExpandableSection>
        )}

        {/* Recommended Instance */}
        <Box>
          <Box variant="awsui-key-label" margin={{ bottom: "xxs" }}>
            Recommended Instance
          </Box>
          <Box fontSize="heading-m" fontWeight="bold">
            {module.recommendedInstance}
          </Box>
          <Box color="text-body-secondary" fontSize="body-s">
            Optimized instance for this module — selected by default
          </Box>
        </Box>

        {/* Instance Selection */}
        <Box>
          <Box variant="awsui-key-label" margin={{ bottom: "xs" }}>
            Select Instance Type
          </Box>
          <RadioGroup
            value={selectedInstance}
            onChange={({ detail }) => handleInstanceChange(detail)}
            items={instanceOptions}
          />
        </Box>

        {/* Storage Options */}
        <Box>
          <Box variant="awsui-key-label" margin={{ bottom: "xs" }}>
            Storage (EBS gp3)
          </Box>
          <Box fontSize="heading-m" fontWeight="bold">
            {storageGB} GB
            {storageAdded > 0 && (
              <Box variant="span" fontSize="body-m" fontWeight="normal">
                {" "}
                (now {storageBaseline} GB, +{storageAdded} GB on Apply)
              </Box>
            )}
          </Box>
          {/* The module's recommendation, kept visibly separate from the volume. Both were
              the same field before, so the panel could not tell the participant "you have
              X, this module wants Y" — it just printed Y and called it the volume. */}
          <Box color="text-body-secondary" fontSize="body-s" margin={{ bottom: "s" }}>
            {liveStorageGB == null
              ? `Provisioned size unavailable — recommended for ${module.title}: ${module.storageGB} GB.`
              : module.storageGB > liveStorageGB
                ? `${module.title} recommends ${module.storageGB} GB — add more below if a notebook runs out of disk.`
                : `Recommended for ${module.title}: ${module.storageGB} GB — your volume already covers it.`}
          </Box>
          <ColumnLayout columns={2}>
            <Button
              onClick={() => handleAddStorage(50)}
              iconName="add-plus"
            >
              +50 GB
            </Button>
            <Button
              onClick={() => handleAddStorage(200)}
              iconName="add-plus"
            >
              +200 GB
            </Button>
          </ColumnLayout>
          <Box color="text-body-secondary" fontSize="body-s" margin={{ top: "xs" }}>
            Additional storage is provisioned as gp3 EBS volumes and attached automatically.
          </Box>
        </Box>

        {/* Change Summary */}
        {canRevert && (
          <Flashbar
            items={[
              {
                type: "warning",
                content: `Will apply: Instance → ${selectedInstance}${
                  storageAdded > 0 ? `, Storage +${storageAdded} GB` : ""
                }.`,
                dismissible: false,
                id: "changes-pending",
              },
            ]}
          />
        )}
      </SpaceBetween>
    </Modal>
  );
}

/**
 * Map the live app status into a Flashbar item shown after Apply. The capacity
 * error gets an actionable hint pointing at the alternative instances (which are
 * already offered in this same panel's radio list).
 */
function buildStatusFlash(
  status: AppStatusResponse | null,
  polling: boolean
): FlashbarProps.MessageDefinition {
  const id = "app-status";

  // A RECORDED failure outranks the app lifecycle. When create_app itself raises there is
  // no app to describe, so `status` is a bland "NotFound" and every branch below would
  // reassure the participant that their workspace is on its way. change_instance's async
  // tail writes the real reason to lastInstanceChangeError; surface it, and say what to do.
  const changeError = status?.lastInstanceChangeError;
  if (changeError && status && status.status !== "InService" && status.status !== "Pending") {
    const sameType = changeError.requestedType === changeError.previousType;
    return {
      id,
      type: "error",
      dismissible: false,
      header: `Could not start ${changeError.requestedType}`,
      content:
        `${changeError.message} ` +
        (changeError.recovered === true
          ? `Your previous instance (${changeError.previousType}) was restored.`
          : sameType
            ? "Nothing was lost — no workspace was running before this attempt. " +
              "Pick a different instance type and apply again."
            : "Pick a different instance type and apply again, or ask the workshop admin " +
              "to free a slot."),
    };
  }

  // Still waiting for the first status, or app is coming up.
  if (!status || status.status === "Pending" || status.status === "Deleting") {
    return {
      id,
      type: "in-progress",
      loading: true,
      dismissible: false,
      header: "Workspace starting…",
      content:
        `Your workspace (${status?.instanceType ?? "GPU instance"}) is launching. ` +
        "This takes a few minutes. When it shows “running”, click “Open Workspace”.",
    };
  }

  if (status.status === "InService") {
    return {
      id,
      type: "success",
      dismissible: false,
      header: "Workspace running",
      content:
        `Your workspace is running on ${status.instanceType}. ` +
        "Close this dialog and click “Open Workspace” to launch JupyterLab.",
    };
  }

  if (status.status === "Failed") {
    if (status.capacityError) {
      return {
        id,
        type: "error",
        dismissible: false,
        header: `${status.instanceType} is temporarily unavailable (capacity)`,
        content:
          "AWS is temporarily out of this instance type in the region. " +
          "Pick an alternative above (e.g. ml.g6.12xlarge) and click " +
          "“Apply & Restart” again — it usually launches right away.",
      };
    }
    return {
      id,
      type: "error",
      dismissible: false,
      header: "Workspace failed to start",
      content:
        status.failureReason ??
        "The workspace failed to launch. Try applying again, or pick a different instance.",
    };
  }

  // NotFound / Deleted — no live app yet.
  return {
    id,
    type: "info",
    dismissible: false,
    header: "No running workspace",
    content: polling
      ? "Waiting for the workspace to be created…"
      : "Apply & Restart to launch your workspace on the selected instance.",
  };
}

function getInstanceDescription(instanceType: string): string {
  const descriptions: Record<string, string> = {
    "ml.t3.medium": "2 vCPU, 4 GiB — Burstable CPU",
    "ml.t3.large": "2 vCPU, 8 GiB — Burstable CPU",
    "ml.t3.xlarge": "4 vCPU, 16 GiB — Burstable CPU",
    "ml.t3.2xlarge": "8 vCPU, 32 GiB — Burstable CPU",
    "ml.m5.large": "2 vCPU, 8 GiB — General purpose CPU",
    "ml.m5.xlarge": "4 vCPU, 16 GiB — General purpose CPU",
    "ml.m5.2xlarge": "8 vCPU, 32 GiB — General purpose CPU",
    "ml.m5.4xlarge": "16 vCPU, 64 GiB — General purpose CPU",
    "ml.c5.large": "2 vCPU, 4 GiB — Compute optimized CPU",
    "ml.c5.xlarge": "4 vCPU, 8 GiB — Compute optimized CPU",
    "ml.c5.2xlarge": "8 vCPU, 16 GiB — Compute optimized CPU",
    "ml.g4dn.xlarge": "4 vCPU, 16 GiB, 1× T4 (16 GB) — GPU inference",
    "ml.g4dn.2xlarge": "8 vCPU, 32 GiB, 1× T4 (16 GB) — GPU inference",
    "ml.g5.xlarge": "4 vCPU, 16 GiB, 1× A10G (24 GB) — GPU compute",
    "ml.g5.2xlarge": "8 vCPU, 32 GiB, 1× A10G (24 GB) — GPU compute",
    "ml.g5.4xlarge": "16 vCPU, 64 GiB, 1× A10G (24 GB) — GPU compute",
    "ml.g5.12xlarge": "48 vCPU, 192 GiB, 4× A10G (96 GB) — multi-GPU",
    "ml.g5.24xlarge": "96 vCPU, 384 GiB, 4× A10G (96 GB) — multi-GPU",
    "ml.g5.48xlarge": "192 vCPU, 768 GiB, 8× A10G (192 GB) — multi-GPU",
    "ml.g6.xlarge": "4 vCPU, 16 GiB, 1× L4 (24 GB) — GPU compute",
    "ml.g6.2xlarge": "8 vCPU, 32 GiB, 1× L4 (24 GB) — GPU compute",
    "ml.g6.4xlarge": "16 vCPU, 64 GiB, 1× L4 (24 GB) — GPU compute",
    "ml.g6.12xlarge": "48 vCPU, 192 GiB, 4× L4 (96 GB) — g5.12xl fallback",
    "ml.g6.24xlarge": "96 vCPU, 384 GiB, 4× L4 (96 GB) — multi-GPU",
    "ml.g6.48xlarge": "192 vCPU, 768 GiB, 8× L4 (192 GB) — multi-GPU",
    // g7e = RTX PRO 6000 Blackwell, 96 GB PER CARD (verified via
    // ec2 describe-instance-types). The per-card figure is what M5/M6/M9 branch
    // on, so it is stated explicitly here: "4× L4 (96 GB)" and
    // "1× RTX PRO 6000 (96 GB)" are the same total but NOT the same capability.
    "ml.g7e.2xlarge": "8 vCPU, 64 GiB, 1× RTX PRO 6000 (96 GB/card) — full-res tier",
    "ml.g7e.4xlarge": "16 vCPU, 128 GiB, 1× RTX PRO 6000 (96 GB/card) — full-res tier",
    "ml.g7e.8xlarge": "32 vCPU, 256 GiB, 1× RTX PRO 6000 (96 GB/card) — full-res tier",
    "ml.g7e.12xlarge": "48 vCPU, 512 GiB, 2× RTX PRO 6000 (96 GB/card) — full-res tier",
    "ml.g7e.24xlarge": "96 vCPU, 1024 GiB, 4× RTX PRO 6000 (96 GB/card) — full-res tier",
    "ml.g7e.48xlarge": "192 vCPU, 2048 GiB, 8× RTX PRO 6000 (96 GB/card) — full-res tier",
    "ml.p3.2xlarge": "8 vCPU, 61 GiB, 1× V100 (16 GB) — ML training",
    "ml.p4d.24xlarge": "96 vCPU, 1152 GiB, 8× A100 (320 GB) — large-scale ML",
    "ml.p5.48xlarge": "192 vCPU, 2 TiB, 8× H100 (640 GB) — frontier training",
  };

  return descriptions[instanceType] ?? "Custom configuration";
}

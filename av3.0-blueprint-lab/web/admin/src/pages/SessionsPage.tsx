import { useState, useEffect, useCallback, useContext, useRef } from "react";
import {
  Box,
  Button,
  Header,
  Pagination,
  SpaceBetween,
  StatusIndicator,
  Table,
  TextFilter,
} from "@cloudscape-design/components";
import { apiClient, Session } from "../api/client";
import { useAuth } from "../auth/CognitoProvider";
import { FlashContext } from "../App";

const PAGE_SIZE = 20;
const POLL_INTERVAL_MS = 30_000;

export function SessionsPage() {
  const { idToken } = useAuth();
  const { addFlash } = useContext(FlashContext);
  const [sessions, setSessions] = useState<Session[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [filterText, setFilterText] = useState("");
  const [currentPage, setCurrentPage] = useState(1);
  const [terminatingId, setTerminatingId] = useState<string | null>(null);
  const pollTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const fetchSessions = useCallback(async () => {
    if (!idToken) return;
    try {
      const data = await apiClient.listSessions(idToken);
      setSessions(data);
    } catch (err) {
      const message = err instanceof Error ? err.message : "Unknown error";
      addFlash({
        type: "error",
        content: `Failed to load sessions: ${message}`,
      });
    } finally {
      setIsLoading(false);
    }
  }, [idToken, addFlash]);

  // Initial load + polling with visibility pause
  useEffect(() => {
    fetchSessions();

    const startPolling = () => {
      if (pollTimerRef.current) return;
      pollTimerRef.current = setInterval(fetchSessions, POLL_INTERVAL_MS);
    };

    const stopPolling = () => {
      if (pollTimerRef.current) {
        clearInterval(pollTimerRef.current);
        pollTimerRef.current = null;
      }
    };

    const handleVisibility = () => {
      if (document.hidden) {
        stopPolling();
      } else {
        fetchSessions(); // Immediate refresh on return
        startPolling();
      }
    };

    startPolling();
    document.addEventListener("visibilitychange", handleVisibility);

    return () => {
      stopPolling();
      document.removeEventListener("visibilitychange", handleVisibility);
    };
  }, [fetchSessions]);

  const handleTerminate = async (sessionId: string) => {
    if (!idToken) return;
    setTerminatingId(sessionId);
    try {
      const res = await apiClient.terminateSession(idToken, sessionId);
      // A 200 does not mean anything was stopped. When no app was running the
      // handler reports terminated:false and deliberately leaves the status alone;
      // announcing "terminated" there is what let a running GPU read as $0.00.
      if (res?.terminated === false) {
        addFlash({
          type: "warning",
          content:
            res.detail ??
            `Nothing was stopped for this session (${res.reason ?? "unknown"}). ` +
              `Their status was left unchanged — verify the app directly before ` +
              `assuming the instance is off.`,
        });
      } else {
        addFlash({ type: "success", content: "Session terminated." });
      }
      await fetchSessions();
    } catch (err) {
      const message = err instanceof Error ? err.message : "Unknown error";
      addFlash({
        type: "error",
        content: `Failed to terminate session: ${message}`,
      });
    } finally {
      setTerminatingId(null);
    }
  };

  // Covers every status list_sessions can write. This previously handled "idle",
  // which the backend never produces, and had no branch for "provisioning" or
  // "stopping" — both real — so a session mid-provision rendered as "stopped".
  const statusType = (status: Session["status"]) => {
    switch (status) {
      case "active":
        return "success";
      case "provisioning":
        return "in-progress";
      case "stopping":
        return "warning";
      case "offline":
        return "stopped";
    }
  };

  const filteredSessions = sessions.filter(
    (s) =>
      s.userName.toLowerCase().includes(filterText.toLowerCase()) ||
      s.instanceType.toLowerCase().includes(filterText.toLowerCase())
  );

  const paginatedSessions = filteredSessions.slice(
    (currentPage - 1) * PAGE_SIZE,
    currentPage * PAGE_SIZE
  );

  // Summary calculations
  const activeSessions = sessions.filter((s) => s.status === "active");
  const gpuSessions = sessions.filter((s) => s.gpuType !== null);
  const todayCost = sessions.reduce((sum, s) => sum + s.costToday, 0);

  return (
    <SpaceBetween size="m">
      {/* Summary bar */}
      <SpaceBetween direction="horizontal" size="l">
        <Box>
          <Box variant="awsui-key-label">Active Sessions</Box>
          <Box variant="awsui-value-large">{activeSessions.length}</Box>
        </Box>
        <Box>
          <Box variant="awsui-key-label">GPU Instances</Box>
          <Box variant="awsui-value-large">{gpuSessions.length}</Box>
        </Box>
        <Box>
          <Box variant="awsui-key-label">Today's Cost</Box>
          <Box variant="awsui-value-large">
            ${todayCost.toFixed(2)}
          </Box>
        </Box>
        <Box>
          <Box variant="awsui-key-label">Auto-refresh</Box>
          <Box variant="small">Every 30s (pauses when tab hidden)</Box>
        </Box>
      </SpaceBetween>

      <Table
        loading={isLoading}
        loadingText="Loading sessions..."
        items={paginatedSessions}
        trackBy="sessionId"
        header={
          <Header
            counter={`(${filteredSessions.length})`}
            actions={
              <Button iconName="refresh" onClick={fetchSessions}>
                Refresh
              </Button>
            }
          >
            Sessions
          </Header>
        }
        filter={
          <TextFilter
            filteringText={filterText}
            onChange={({ detail }) => {
              setFilterText(detail.filteringText);
              setCurrentPage(1);
            }}
            filteringPlaceholder="Search by user or instance type"
          />
        }
        pagination={
          <Pagination
            currentPageIndex={currentPage}
            pagesCount={Math.ceil(filteredSessions.length / PAGE_SIZE)}
            onChange={({ detail }) => setCurrentPage(detail.currentPageIndex)}
          />
        }
        columnDefinitions={[
          {
            id: "user",
            header: "User",
            cell: (s) => s.userName,
            sortingField: "userName",
          },
          {
            id: "status",
            header: "Status",
            cell: (s) => (
              <StatusIndicator type={statusType(s.status)}>
                {s.status}
              </StatusIndicator>
            ),
          },
          {
            id: "region",
            header: "Region",
            cell: (s) => s.region || "—",
            sortingField: "region",
          },
          {
            id: "instanceType",
            header: "Instance Type",
            cell: (s) => s.instanceType,
          },
          {
            id: "gpu",
            header: "GPU",
            cell: (s) => s.gpuType ?? "-",
          },
          {
            id: "started",
            header: "Started",
            cell: (s) => new Date(s.startedAt).toLocaleString(),
          },
          {
            id: "cost",
            header: "Cost Today",
            cell: (s) => `$${s.costToday.toFixed(2)}`,
          },
          {
            id: "actions",
            header: "Actions",
            cell: (s) => (
              <Button
                variant="inline-link"
                loading={terminatingId === s.sessionId}
                onClick={() => handleTerminate(s.sessionId)}
                disabled={s.status === "offline"}
              >
                Terminate
              </Button>
            ),
          },
        ]}
        empty={
          <Box textAlign="center" color="inherit">
            <b>No active sessions</b>
            <Box variant="p" color="inherit">
              Sessions will appear when users connect.
            </Box>
          </Box>
        }
      />
    </SpaceBetween>
  );
}

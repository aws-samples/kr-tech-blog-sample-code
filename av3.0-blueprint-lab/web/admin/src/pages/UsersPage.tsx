import { useState, useEffect, useCallback, useContext, useRef } from "react";
import {
  Box,
  Button,
  CopyToClipboard,
  Header,
  Modal,
  Pagination,
  SpaceBetween,
  StatusIndicator,
  Table,
  TextFilter,
} from "@cloudscape-design/components";
import { apiClient, ApiError, User } from "../api/client";
import { participantLink } from "../config";
import { useAuth } from "../auth/CognitoProvider";
import { FlashContext } from "../App";
import { ProvisionModal } from "../components/ProvisionModal";
import { BulkUploadModal } from "../components/BulkUploadModal";

const PAGE_SIZE = 20;

// Delete runs asynchronously server-side; these bound the wait for its outcome.
// The deadline exceeds the backend's worst case (app 240s + space 180s + profile 180s
// = 600s) so a slow-but-healthy teardown is reported as done, not as a timeout.
const DELETE_POLL_MS = 5_000;
const DELETE_POLL_DEADLINE_MS = 12 * 60 * 1_000;

export function UsersPage() {
  const { idToken } = useAuth();
  const { addFlash } = useContext(FlashContext);
  const [users, setUsers] = useState<User[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [filterText, setFilterText] = useState("");
  const [currentPage, setCurrentPage] = useState(1);
  const [sortingColumn, setSortingColumn] = useState<string>("name");
  const [sortingDescending, setSortingDescending] = useState(false);
  const [showProvision, setShowProvision] = useState(false);
  const [showBulkUpload, setShowBulkUpload] = useState(false);
  const [resettingUserId, setResettingUserId] = useState<string | null>(null);
  const [confirmDeleteUser, setConfirmDeleteUser] = useState<User | null>(null);
  const [deletingUserId, setDeletingUserId] = useState<string | null>(null);

  const fetchUsers = useCallback(async () => {
    if (!idToken) return;
    try {
      const data = await apiClient.listUsers(idToken);
      setUsers(data);
    } catch (err) {
      const message = err instanceof Error ? err.message : "Unknown error";
      addFlash({ type: "error", content: `Failed to load users: ${message}` });
    } finally {
      setIsLoading(false);
    }
  }, [idToken, addFlash]);

  useEffect(() => {
    fetchUsers();
  }, [fetchUsers]);

  // Stops delete polling when this page unmounts. A teardown can outlive the admin's
  // visit to the Users tab, and the loop would otherwise keep refetching and writing
  // state for a component nobody is looking at.
  const pollCancelled = useRef(false);
  useEffect(() => {
    pollCancelled.current = false;
    return () => {
      pollCancelled.current = true;
    };
  }, []);

  const handleReset = async (userId: string) => {
    if (!idToken) return;
    setResettingUserId(userId);
    try {
      const res = await apiClient.resetWorkspace(idToken, userId);
      // A reset only rewrites S3. If the participant's app is up it still shows the OLD
      // files and still holds its GPU memory, so saying just "reset" would be misleading.
      addFlash(
        res?.appRunning
          ? {
              type: "warning",
              content:
                `Workspace files replaced in S3 (${res.filesCopied} copied). ` +
                "Their workspace is STILL RUNNING, so it has the old files and its kernels " +
                "still hold any GPU memory. It must restart for the new files to appear: " +
                "Stop space then Run space in SageMaker Studio, or terminate the session " +
                "from the Sessions tab and have them press Start Workspace.",
            }
          : {
              type: "success",
              content:
                `Workspace reset (${res?.filesCopied ?? 0} files staged). ` +
                "No app is running, so they get the fresh files the next time they start it.",
            }
      );
      await fetchUsers();
    } catch (err) {
      const message = err instanceof Error ? err.message : "Unknown error";
      addFlash({ type: "error", content: `Reset failed: ${message}` });
    } finally {
      setResettingUserId(null);
    }
  };

  /**
   * Poll GET /users until the row for `userId` disappears (teardown finished) or turns
   * "delete-failed" (teardown stopped, reason on the row).
   *
   * Needed because DELETE /users/{id} no longer completes the work: it dispatches an
   * async teardown and returns in under a second. The response therefore cannot say
   * whether the delete succeeded — only the row can.
   *
   * A listUsers failure mid-poll is skipped rather than fatal: the teardown is running
   * server-side regardless, so one failed refresh is not an outcome.
   */
  const waitForDeletion = async (
    token: string,
    userId: string
  ): Promise<{ outcome: "gone" | "failed" | "timeout" | "cancelled"; error?: string }> => {
    const deadline = Date.now() + DELETE_POLL_DEADLINE_MS;
    while (Date.now() < deadline) {
      await new Promise((resolve) => setTimeout(resolve, DELETE_POLL_MS));
      if (pollCancelled.current) return { outcome: "cancelled" };
      let latest: User[];
      try {
        latest = await apiClient.listUsers(token);
      } catch {
        continue;
      }
      if (pollCancelled.current) return { outcome: "cancelled" };
      setUsers(latest);
      const row = latest.find((u) => u.userId === userId);
      if (!row) return { outcome: "gone" };
      if (row.status === "delete-failed") {
        return { outcome: "failed", error: row.lastDeleteError };
      }
    }
    return { outcome: "timeout" };
  };

  /**
   * Delete a user and follow the teardown to its actual end.
   *
   * MEASURED (2026-09-26): the old version reported a COMPLETE, CORRECT delete as
   * "Delete failed". The teardown ran on the request path and took 32.5s for a user whose
   * GPU app was up, against API Gateway's 29s integration cap, so the browser got a 504
   * four seconds before the Lambda succeeded. The modal stayed open and the list was never
   * refreshed (both happened only inside the try), so the admin re-clicked Delete and got
   * "404 User not found" — the row had already gone. Three times.
   *
   * So: the modal closes and the list refreshes on EVERY outcome, a 404 counts as already
   * deleted rather than an error, and success is decided by the row disappearing.
   */
  const handleDelete = async (user: User) => {
    if (!idToken) return;
    setDeletingUserId(user.userId);
    setConfirmDeleteUser(null);
    try {
      const res = await apiClient.deleteUser(idToken, user.userId);

      // Defensive: a browser holding an older bundle can reach a backend that still
      // completed the teardown synchronously. Then there is nothing to wait for.
      if (res?.deleted) {
        addFlash({ type: "success", content: `User ${user.name} deleted.` });
        await fetchUsers();
        return;
      }

      addFlash({
        type: "info",
        content: res?.alreadyInProgress
          ? `A delete for ${user.name} was already running; waiting for it to finish.`
          : `Deleting ${user.name}. Shutting down their workspace, space and profile ` +
            `takes about a minute${res?.appWasRunning ? " — their app was running" : ""}.`,
      });
      await fetchUsers(); // flip the row to "deleting" without waiting for the first poll

      const { outcome, error } = await waitForDeletion(idToken, user.userId);
      if (outcome === "gone") {
        addFlash({ type: "success", content: `User ${user.name} deleted.` });
      } else if (outcome === "failed") {
        addFlash({
          type: "error",
          content:
            `Deleting ${user.name} stopped partway: ${error || "reason not recorded"} ` +
            `Press Delete again to resume — every step is idempotent.`,
        });
      } else if (outcome === "timeout") {
        addFlash({
          type: "warning",
          content:
            `Still deleting ${user.name} after several minutes. It is running in the ` +
            `background; reload this page to see the result.`,
        });
      }
    } catch (err) {
      const message = err instanceof Error ? err.message : "Unknown error";
      // 404 = the row is already gone, which for a delete is the goal, not a failure.
      // This is the exact banner the admin saw after a delete that had succeeded.
      if (err instanceof ApiError && err.statusCode === 404) {
        addFlash({
          type: "info",
          content: `${user.name} was already deleted. Refreshing the list.`,
        });
      } else {
        addFlash({ type: "error", content: `Delete failed: ${message}` });
      }
      await fetchUsers();
    } finally {
      setDeletingUserId(null);
    }
  };

  const statusType = (status: User["status"]) => {
    switch (status) {
      case "active":
        return "success";
      case "idle":
        return "warning";
      case "provisioning":
      case "deleting":
        return "in-progress";
      case "delete-failed":
        return "error";
      default:
        return "stopped";
    }
  };

  const filteredUsers = users.filter(
    (u) =>
      u.name.toLowerCase().includes(filterText.toLowerCase()) ||
      u.email.toLowerCase().includes(filterText.toLowerCase()) ||
      u.module.toLowerCase().includes(filterText.toLowerCase())
  );

  const sortedUsers = [...filteredUsers].sort((a, b) => {
    const key = sortingColumn as keyof User;
    const aVal = String(a[key] ?? "");
    const bVal = String(b[key] ?? "");
    const cmp = aVal.localeCompare(bVal);
    return sortingDescending ? -cmp : cmp;
  });

  const paginatedUsers = sortedUsers.slice(
    (currentPage - 1) * PAGE_SIZE,
    currentPage * PAGE_SIZE
  );

  return (
    <>
      <Table
        loading={isLoading}
        loadingText="Loading users..."
        items={paginatedUsers}
        trackBy="userId"
        sortingColumn={{ sortingField: sortingColumn }}
        sortingDescending={sortingDescending}
        onSortingChange={({ detail }) => {
          setSortingColumn(detail.sortingColumn.sortingField ?? "name");
          setSortingDescending(detail.isDescending ?? false);
        }}
        header={
          <Header
            counter={`(${filteredUsers.length})`}
            actions={
              <SpaceBetween direction="horizontal" size="xs">
                <Button onClick={() => setShowBulkUpload(true)}>
                  Bulk Upload
                </Button>
                <Button variant="primary" onClick={() => setShowProvision(true)}>
                  Add User
                </Button>
              </SpaceBetween>
            }
          >
            Users
          </Header>
        }
        filter={
          <TextFilter
            filteringText={filterText}
            onChange={({ detail }) => {
              setFilterText(detail.filteringText);
              setCurrentPage(1);
            }}
            filteringPlaceholder="Search by name, email, or module"
          />
        }
        pagination={
          <Pagination
            currentPageIndex={currentPage}
            pagesCount={Math.ceil(filteredUsers.length / PAGE_SIZE)}
            onChange={({ detail }) => setCurrentPage(detail.currentPageIndex)}
          />
        }
        columnDefinitions={[
          {
            id: "name",
            header: "Name",
            cell: (u) => u.name,
            sortingField: "name",
          },
          {
            id: "email",
            header: "Email",
            cell: (u) => u.email,
            sortingField: "email",
          },
          {
            id: "status",
            header: "Status",
            // lastDeleteError is shown INLINE, not as a flash: the teardown is async, so
            // the reason arrives long after any request the admin made, and a failed
            // OpenSearch Serverless cleanup keeps billing at its 2-OCU floor until
            // someone acts on it. It has to stay on screen.
            cell: (u) => (
              <SpaceBetween size="xxxs">
                <StatusIndicator type={statusType(u.status)}>
                  {u.status}
                </StatusIndicator>
                {u.status === "delete-failed" && u.lastDeleteError ? (
                  <Box fontSize="body-s" color="text-status-error">
                    {u.lastDeleteError}
                  </Box>
                ) : null}
              </SpaceBetween>
            ),
            sortingField: "status",
          },
          {
            id: "module",
            header: "Module",
            cell: (u) => u.module || "-",
            sortingField: "module",
          },
          {
            // Read-only on purpose: a UserProfile belongs to one regional Domain, so
            // the region is fixed at provisioning and only delete + re-provision can
            // change it. Shown because a mis-regioned user otherwise looks healthy.
            id: "region",
            header: "Region",
            cell: (u) => u.region || "—",
            sortingField: "region",
          },
          {
            id: "dashboardLink",
            header: "Dashboard Link",
            cell: (u) =>
              u.participantToken ? (
                <CopyToClipboard
                  copyButtonText="Copy link"
                  copySuccessText="Copied!"
                  copyErrorText="Failed to copy"
                  textToCopy={participantLink(u.userId, u.participantToken)}
                  variant="button"
                />
              ) : (
                "-"
              ),
          },
          {
            id: "actions",
            header: "Actions",
            cell: (u) => (
              <SpaceBetween direction="horizontal" size="xs">
                <Button
                  variant="inline-link"
                  loading={resettingUserId === u.userId}
                  disabled={deletingUserId === u.userId}
                  onClick={() => handleReset(u.userId)}
                >
                  Reset
                </Button>
                <Button
                  variant="inline-link"
                  loading={deletingUserId === u.userId}
                  disabled={resettingUserId === u.userId}
                  onClick={() => setConfirmDeleteUser(u)}
                >
                  Delete
                </Button>
              </SpaceBetween>
            ),
          },
        ]}
        empty={
          <Box textAlign="center" color="inherit">
            <b>No users</b>
            <Box variant="p" color="inherit">
              Add users to get started.
            </Box>
          </Box>
        }
      />

      <ProvisionModal
        visible={showProvision}
        onDismiss={() => setShowProvision(false)}
        onSuccess={fetchUsers}
      />
      <BulkUploadModal
        visible={showBulkUpload}
        onDismiss={() => setShowBulkUpload(false)}
        onSuccess={fetchUsers}
      />

      <Modal
        visible={confirmDeleteUser !== null}
        onDismiss={() => {
          if (deletingUserId === null) setConfirmDeleteUser(null);
        }}
        header="Delete user"
        footer={
          <Box float="right">
            <SpaceBetween direction="horizontal" size="xs">
              <Button
                variant="link"
                disabled={deletingUserId !== null}
                onClick={() => setConfirmDeleteUser(null)}
              >
                Cancel
              </Button>
              <Button
                variant="primary"
                loading={deletingUserId !== null}
                onClick={() => {
                  if (confirmDeleteUser) void handleDelete(confirmDeleteUser);
                }}
              >
                Delete
              </Button>
            </SpaceBetween>
          </Box>
        }
      >
        {confirmDeleteUser && (
          <SpaceBetween size="s">
            <Box>
              Permanently delete <strong>{confirmDeleteUser.name}</strong> (
              {confirmDeleteUser.email})?
            </Box>
            <Box color="text-status-error">
              This removes their SageMaker workspace, notebooks, and any generated
              output, and cannot be undone.
            </Box>
          </SpaceBetween>
        )}
      </Modal>
    </>
  );
}

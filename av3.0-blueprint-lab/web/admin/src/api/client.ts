import { getConfig } from "../config";

export interface User {
  userId: string;
  name: string;
  email: string;
  /**
   * Auth/lifecycle state from the session row. "deleting" and "delete-failed" are
   * written by delete_user's two paths: the request path marks the row before handing
   * the teardown to an async self-invocation, and the tail either removes the row or
   * leaves it as "delete-failed" with lastDeleteError set.
   */
  status:
    | "active"
    | "idle"
    | "offline"
    | "provisioning"
    | "deleting"
    | "delete-failed";
  module: string;
  workspaceUrl: string;
  createdAt: string;
  /**
   * Why the last teardown stopped, present only alongside status "delete-failed".
   * Load-bearing rather than cosmetic: the teardown runs asynchronously, so there is no
   * HTTP response left to carry the reason, and an incomplete OpenSearch Serverless
   * cleanup leaves a collection billing at its 2-OCU floor. Pressing Delete again
   * retries — every step swallows ResourceNotFound, so it resumes where it stopped.
   */
  lastDeleteError?: string;
  // Durable participant token used to build the user dashboard link. Optional
  // because rows provisioned before this field was added won't have it.
  participantToken?: string;
  /**
   * Region of this user's SageMaker Studio domain. "" for rows provisioned before the
   * attribute existed. Read-only — see CreateUserRequest.region for why it cannot change.
   */
  region?: string;
}

/**
 * One row of GET /sessions. These names are a CONTRACT with
 * infra/lambda/list_sessions/handler.py — they did not match it until recently, and
 * because TypeScript cannot see across that boundary every mismatch compiled fine
 * and failed at runtime: `costToday` was absent, so `s.costToday.toFixed(2)` threw
 * inside the table's cell renderer and blanked the page; `sessionId` was absent, so
 * the terminate button requested /sessions/undefined; and `gpuType` was absent, so
 * the "GPU sessions" count matched every row (undefined !== null). Change both sides
 * together.
 */
export interface Session {
  /** Same value as userId — what the table trackBy and the action buttons use. */
  sessionId: string;
  userId: string;
  userName: string;
  instanceType: string;
  /**
   * Every state the backend actually writes. "idle" is NOT one of them — it was in
   * this union while "provisioning" and "stopping" (both written by create_user and
   * change_instance) were missing, so real rows fell outside the declared type.
   */
  status: "active" | "offline" | "provisioning" | "stopping";
  startedAt: string;
  /** GPU model (e.g. "L4", "A100"), or null for a CPU instance. */
  gpuType: string | null;
  /** Spend since 00:00 UTC today — matches the "Cost Today" column and tile. */
  costToday: number;
  /** Spend since the participant was provisioned. Not currently displayed. */
  estimatedCostTotal?: number;
  currentModule?: string | null;
  storageGB?: number;
  /** Region this session's instance actually runs in. "" for pre-existing rows. */
  region?: string;
}

export interface DailyCost {
  date: string;
  /** Total account spend for that day, USD. */
  cost: number;
  /** Per-service breakdown for the day, e.g. {"Amazon SageMaker": 268.12}. */
  byService?: Record<string, number>;
}

export interface BulkProvisionResult {
  succeeded: Array<{ email: string; name: string; workspaceUrl: string }>;
  failed: Array<{ email: string; name: string; error: string }>;
}

export interface CreateUserRequest {
  name: string;
  email: string;
  module?: string;
  /**
   * AWS region for this participant's SageMaker Studio domain. Optional; the backend
   * defaults to the control-plane region and rejects a region it does not manage.
   *
   * IMMUTABLE once provisioned: a UserProfile belongs to exactly one Domain and a
   * Domain is regional, so there is no "move this participant" operation — only
   * delete and re-provision. There is deliberately no PATCH route for it.
   */
  region?: string;
}

/**
 * Body of POST /sessions/{id}/terminate.
 *
 * `terminated: false` with HTTP 200 is a normal outcome, not an error: it means no
 * running JupyterLab app was found, so nothing was stopped and the user's status was
 * left as-is on purpose. It must be shown differently from a real termination.
 */
export interface TerminateSessionResult {
  terminated: boolean;
  userId: string;
  /** Present when terminated is false, e.g. "no-running-app". */
  reason?: string;
  /** Operator-facing explanation, including the describe-app command to check. */
  detail?: string;
}

/**
 * Body of DELETE /users/{id}.
 *
 * `deleted` is FALSE on the happy path. The route only starts the teardown: it issues
 * the app delete, marks the row "deleting" and hands the rest to an async
 * self-invocation, because the full teardown measured 32.5s for a user with a running
 * GPU app and API Gateway's REST integration is capped at 29s. Watch GET /users for the
 * row to disappear (success) or turn "delete-failed" (with lastDeleteError).
 *
 * `filesDeleted` and `aoss` therefore only appear on legacy synchronous responses;
 * neither is available when the work has merely been dispatched.
 */
export interface DeleteUserResult {
  deleted: boolean;
  userId: string;
  filesDeleted?: number;
  /** True when the teardown was handed to the async tail rather than completed here. */
  async?: boolean;
  /** True when a teardown for this user was already running; nothing new was started. */
  alreadyInProgress?: boolean;
  /** Whether an app was actually running and had to be shut down first. */
  appWasRunning?: boolean;
  /**
   * OpenSearch Serverless teardown, which is deliberately best-effort so an AOSS
   * hiccup cannot block the SageMaker/S3/DynamoDB teardown. `complete: false` means a
   * collection or policy may still exist — and an orphaned AOSS collection bills at a
   * 2-OCU floor indefinitely, so this must be shown to the admin, not swallowed.
   * `reasons` carries AWS error CODES (e.g. "AccessDeniedException",
   * "ConflictException"); ConflictException is expected right after a delete, while
   * the collection is still DELETING, and the teardown.sh sweep reaps it later.
   *
   * "Not found" is deliberately NOT reported: most participants never reach M4, so no
   * collection or policy was ever created and every delete would come back
   * ResourceNotFoundException. Treating that as incomplete made this warning fire on
   * every single deletion, which trains admins to ignore it. So `complete: false` now
   * means a resource plausibly still exists.
   */
  aoss?: {
    collection: string;
    collectionFound: boolean;
    collectionDeleted: boolean;
    policiesDeleted: string[];
    complete: boolean;
    reasons: string[];
  };
}

export interface ResetWorkspaceResponse {
  userId: string;
  message: string;
  filesDeleted: number;
  filesCopied: number;
  // True when the participant's JupyterLab app is still up. Everything a reset does happens
  // in S3; the participant's home is populated by the notebook-sync lifecycle config, which
  // runs only at app START. So with appRunning true the reset is real but INVISIBLE to them,
  // and their kernels still hold any GPU memory. Surfaced because reporting a bare
  // "Workspace reset successfully" led to a reset being retried as though it had failed.
  appRunning?: boolean;
  note?: string;
}

class AdminApiClient {
  private getHeaders(idToken: string): HeadersInit {
    return {
      "Content-Type": "application/json",
      Authorization: `Bearer ${idToken}`,
    };
  }

  private getBaseUrl(): string {
    return getConfig().apiBaseUrl;
  }

  private async request<T>(
    method: string,
    path: string,
    idToken: string,
    body?: unknown
  ): Promise<T> {
    const url = `${this.getBaseUrl()}${path}`;
    const options: RequestInit = {
      method,
      headers: this.getHeaders(idToken),
    };

    if (body) {
      options.body = JSON.stringify(body);
    }

    const response = await fetch(url, options);

    if (!response.ok) {
      const errorBody = await response.text();
      let message: string;
      try {
        const parsed = JSON.parse(errorBody);
        message = parsed.message ?? parsed.error ?? errorBody;
      } catch {
        message = errorBody || `HTTP ${response.status}`;
      }
      throw new ApiError(message, response.status);
    }

    if (response.status === 204) {
      return undefined as T;
    }

    return response.json() as Promise<T>;
  }

  async createUser(
    idToken: string,
    data: CreateUserRequest
  ): Promise<User> {
    return this.request<User>("POST", "/users", idToken, data);
  }

  async bulkProvision(
    idToken: string,
    users: Array<{ name: string; email: string; module?: string; region?: string }>,
    region?: string
  ): Promise<BulkProvisionResult> {
    // `region` is the batch-wide default; a per-row region still wins. The backend
    // validates both against the managed set and rejects the whole upload on a typo,
    // rather than provisioning half a room into the wrong region.
    return this.request<BulkProvisionResult>(
      "POST",
      "/users/bulk",
      idToken,
      region ? { users, region } : { users }
    );
  }

  async listUsers(idToken: string): Promise<User[]> {
    const data = await this.request<User[] | { users: User[] }>("GET", "/users", idToken);
    return Array.isArray(data) ? data : (data?.users ?? []);
  }

  async listSessions(idToken: string): Promise<Session[]> {
    const data = await this.request<Session[] | { sessions: Session[] }>("GET", "/sessions", idToken);
    return Array.isArray(data) ? data : (data?.sessions ?? []);
  }

  /**
   * Stop a participant's running JupyterLab app. Backend:
   * POST /sessions/{id}/terminate (Cognito auth).
   *
   * The method and path are both load-bearing. This previously sent
   * DELETE /sessions/{id} — a route the API does not expose at all (api.py adds no
   * method to /sessions/{id}, only to its /terminate child), so API Gateway answered
   * 403 "Missing Authentication Token" and the only UI lever for stopping a running
   * GPU never worked.
   *
   * Returns the body rather than void: a 200 does NOT mean something was stopped.
   * When no app was running the handler reports `terminated: false` with a reason,
   * deliberately leaving the user's status untouched — reporting that as success is
   * what previously let a running GPU display as offline at $0.00/hr.
   */
  async terminateSession(
    idToken: string,
    sessionId: string
  ): Promise<TerminateSessionResult> {
    return this.request<TerminateSessionResult>(
      "POST",
      `/sessions/${sessionId}/terminate`,
      idToken
    );
  }

  async getDailyCosts(idToken: string, days: number = 14): Promise<DailyCost[]> {
    const data = await this.request<DailyCost[] | { costs: DailyCost[] }>(
      "GET",
      `/costs/daily?days=${days}`,
      idToken
    );
    return Array.isArray(data) ? data : (data?.costs ?? []);
  }

  async resetWorkspace(
    idToken: string,
    userId: string
  ): Promise<ResetWorkspaceResponse> {
    return this.request<ResetWorkspaceResponse>(
      "POST",
      `/users/${userId}/reset`,
      idToken
    );
  }

  /**
   * Permanently delete a user and all their resources (SageMaker app/space/
   * profile, S3 workspace files, DynamoDB row). Backend: DELETE /users/{id}
   * (Cognito auth). Not reversible.
   *
   * Returns the body rather than void: the handler's OpenSearch Serverless teardown
   * is best-effort and reports `aoss.complete === false` when a collection may still
   * exist. An orphaned AOSS collection bills at a 2-OCU floor indefinitely, so that
   * signal must reach the admin instead of being thrown away.
   */
  async deleteUser(idToken: string, userId: string): Promise<DeleteUserResult> {
    return this.request<DeleteUserResult>("DELETE", `/users/${userId}`, idToken);
  }
}

export class ApiError extends Error {
  constructor(
    message: string,
    public readonly statusCode: number
  ) {
    super(message);
    this.name = "ApiError";
  }
}

export const apiClient = new AdminApiClient();

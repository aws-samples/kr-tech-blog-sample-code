interface WorkspaceUrlResponse {
  userId: string;
  presignedUrl: string;
  expiresAt: string;
}

interface ProgressUpdate {
  moduleId: string;
  status: "completed" | "in-progress" | "locked";
}

interface InstanceChangeResponse {
  updated: boolean;
  previousType: string;
  newType: string;
}

interface StorageExpansionResponse {
  updated: boolean;
  previousSizeGB: number;
  newSizeGB: number;
}

interface InstanceOptionsResponse {
  moduleId: string;
  moduleName: string;
  defaultInstanceType: string;
  estimatedDurationMinutes: number;
  availableInstances: {
    instanceType: string;
    hourlyCost: number;
    isDefault: boolean;
  }[];
}

export interface AppStatusResponse {
  userId: string;
  // Participant display name (from the DDB session row). May be null for older
  // rows created before names were stored.
  name?: string | null;
  // B2: live per-module progress from the DDB session row, keyed by the canonical
  // long id (m01-data-exploration..m11-orchestration). Wire values are
  // "in_progress" | "completed"; App.tsx normalizes and falls back to static.
  moduleProgress?: Record<string, string>;
  // SageMaker app lifecycle: Pending | InService | Deleting | Deleted | Failed,
  // plus "NotFound" when no app exists yet (never launched or auto-deleted).
  status: string;
  instanceType: string;
  failureReason: string | null;
  isGpu: boolean;
  // True when failureReason is an AWS capacity shortage (EC2InsufficientCapacity)
  // — the UI should suggest switching to an alternative instance.
  capacityError: boolean;
  // Why the last instance change failed, written by change_instance's async tail.
  //
  // This is the ONLY explanation a failed change produces, and it is the only signal for
  // the failure mode where NO app exists to describe (create_app itself raised, so
  // `status` is a bland "NotFound"). The backend has always returned it
  // (infra/lambda/app_status/handler.py); it was missing from this interface, so the panel
  // rendered "Waiting for the workspace to be created…" over a recorded, specific failure.
  // The space's ACTUAL provisioned EBS volume, in GB, from describe_space. null when it
  // could not be read.
  //
  // This is NOT pipeline-config.ts's per-module `storageGB`, which is only a recommended
  // capacity. Conflating the two is what made the panel display "100 GB" for a space whose
  // real volume was 5 GB, and made the +50/+200 buttons compute against the wrong base.
  storageGB?: number | null;
  lastInstanceChangeError?: {
    requestedType: string;
    previousType: string;
    message: string;
    // true = rolled back to previousType; false = rollback also failed;
    // null = nothing to roll back to (a same-type start, so no app was running before).
    recovered: boolean | null;
    failedAt: string;
  } | null;
}

export class ApiClient {
  private baseUrl: string;
  private token: string;

  constructor(apiBaseUrl: string, token: string) {
    this.baseUrl = apiBaseUrl;
    this.token = token;
  }

  private async request<T>(path: string, options: RequestInit = {}): Promise<T> {
    const response = await fetch(`${this.baseUrl}${path}`, {
      ...options,
      headers: {
        "Content-Type": "application/json",
        "X-Api-Key": this.token,
        ...options.headers,
      },
    });

    if (!response.ok) {
      const errorBody = await response.text();
      throw new ApiError(response.status, errorBody);
    }

    return response.json() as Promise<T>;
  }

  /**
   * Generate a FRESH presigned workspace URL on demand. Called at click time so
   * the 5-minute redeem window is never an issue, and re-opening later just
   * re-calls it. Backend: POST /presigned-url/{userId} (Token auth).
   */
  async getWorkspaceUrl(userId: string): Promise<WorkspaceUrlResponse> {
    return this.request<WorkspaceUrlResponse>(`/presigned-url/${userId}`, {
      method: "POST",
    });
  }

  async updateProgress(
    userId: string,
    moduleId: string,
    status: ProgressUpdate["status"]
  ): Promise<ProgressUpdate> {
    return this.request<ProgressUpdate>(`/sessions/${userId}/progress`, {
      method: "POST",
      body: JSON.stringify({ moduleId, status }),
    });
  }

  async changeInstance(
    userId: string,
    newInstanceType: string
  ): Promise<InstanceChangeResponse> {
    return this.request<InstanceChangeResponse>(
      `/sessions/${userId}/instance-type`,
      {
        method: "PATCH",
        body: JSON.stringify({ newInstanceType }),
      }
    );
  }

  async expandStorage(
    userId: string,
    addGB: number
  ): Promise<StorageExpansionResponse> {
    return this.request<StorageExpansionResponse>(`/sessions/${userId}/storage`, {
      method: "PATCH",
      body: JSON.stringify({ addGB }),
    });
  }

  async getInstanceOptions(moduleId: string): Promise<InstanceOptionsResponse> {
    return this.request<InstanceOptionsResponse>(
      `/modules/${moduleId}/instance-options`
    );
  }

  /**
   * Live SageMaker app health for the user's workspace. Backend:
   * GET /sessions/{userId}/app-status (Token auth). Used to poll after an
   * instance change so the participant sees Pending/InService/Failed instead
   * of a static "In Progress".
   */
  async getAppStatus(userId: string): Promise<AppStatusResponse> {
    return this.request<AppStatusResponse>(`/sessions/${userId}/app-status`);
  }
}

export class ApiError extends Error {
  public readonly status: number;
  public readonly body: string;

  constructor(status: number, body: string) {
    super(`API Error ${status}: ${body}`);
    this.name = "ApiError";
    this.status = status;
    this.body = body;
  }
}

> **English** | [한국어](../ko/ARCHITECTURE.md)

# DevOps Agent Operator Internals

This document explains the end-to-end flow of how DevOps Agent Operator detects abnormal Pod states, collects troubleshooting data, and delivers it to external systems.

---

## Overall Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                        Kubernetes API Server                        │
│                                                                     │
│  Propagates events through Informer when Pod resources change       │
└───────────────┬─────────────────────────────────────────────────────┘
                │ List & Watch (Pod)
                ▼
┌─────────────────────────────────────────────────────────────────────┐
│                      controller-runtime Manager                     │
│                                                                     │
│  ┌──────────────┐    ┌──────────────┐    ┌───────────────────────┐  │
│  │   Informer   │───▶│ EventFilter  │───▶│     Work Queue        │  │
│  │  (Pod Watch) │    │ (predicate)  │    │ (NamespacedName queue)│  │
│  └──────────────┘    └──────────────┘    └──────────┬────────────┘  │
│                                                     │               │
│                                          Worker goroutine           │
│                                                     │               │
│                                                     ▼               │
│                                          ┌──────────────────────┐   │
│                                          │  Reconcile(ctx, req) │   │
│                                          └──────────────────────┘   │
└─────────────────────────────────────────────────────────────────────┘
                                                      │
                                                      ▼
                          ┌───────────────────────────────────────┐
                          │            PodReconciler              │
                          │                                       │
                          │  1. Namespace filtering               │
                          │  2. Duplicate-processing check        │
                          │  3. Failure detection                 │
                          │     (detectPodFailure)                │
                          │  4. Data collection                   │
                          │     (buildCollectedData)              │
                          │  5. Output                            │
                          │     (CloudWatch, S3, Webhook)         │
                          │  6. Mark as processed                 │
                          └───────────────────────────────────────┘
```

---

## Step 1: Startup — Manager Initialization

When the Operator process starts, `cmd/main.go` initializes components in the following order.

```
main()
  ├─ ctrl.NewManager()              # Create controller-runtime Manager
  ├─ config.LoadFromEnv()           # Load configuration from environment variables
  ├─ Create collector/output clients # LogCollector, SSM, S3, CloudWatch, Webhook
  ├─ PodReconciler{}.SetupWithManager(mgr)   # Register controller
  └─ mgr.Start()                    # Start the Manager → enter the event loop
```

`SetupWithManager()` is the key registration point:

```go
// internal/controller/pod_controller.go

func (r *PodReconciler) SetupWithManager(mgr ctrl.Manager) error {
    return ctrl.NewControllerManagedBy(mgr).
        For(&corev1.Pod{}).                    // "Watch the Pod resource"
        WithEventFilter(predicate.Funcs{...}). // Register event filter
        Complete(r)                            // r = the Reconciler implementation
}
```

What this call does internally:

| Step | Description |
|------|-------------|
| `For(&corev1.Pod{})` | Creates a SharedInformer for Pods. Establishes a List/Watch connection with the API Server |
| `WithEventFilter(...)` | Registers filter conditions applied before events enter the queue |
| `Complete(r)` | Registers `r` as the Reconciler. Internally starts the worker goroutine |

After `mgr.Start()`, the Informer connects to the API Server and receives Pod change events in real time.

---

## Step 2: Event Filtering — hasFailureStateChanged

In a Kubernetes cluster, Pods are updated frequently (readiness probe results, label changes, resource status updates, etc.). Running Reconcile for every event would create unnecessary load.

The predicate in `WithEventFilter` prevents this:

```go
WithEventFilter(predicate.Funcs{
    CreateFunc:  func(e event.CreateEvent) bool  { return false },  // ignore creates
    UpdateFunc:  func(e event.UpdateEvent) bool  {
        return r.hasFailureStateChanged(oldPod, newPod)             // only pass through failure-state changes
    },
    DeleteFunc:  func(e event.DeleteEvent) bool  { return false },  // ignore deletes
    GenericFunc: func(e event.GenericEvent) bool { return false },  // ignore others
})
```

**Why ignore Create**: When a Pod is first created, scheduling and container startup haven't completed yet, so it isn't in a failure state. Subsequent state changes will be detected as Update events.

### hasFailureStateChanged Decision Logic

```
Run detectPodFailure() against both oldPod and newPod
                    │
    ┌───────────────┼───────────────────────┐
    ▼               ▼                       ▼
 Both: no failure  No failure → failure   Both have a failure
    │               │                       │
    │               └─▶ return true         │
    │                  (new failure)        │
    │                                       │
    ▼                                       ▼
 ContainerCreating                Type or Container changed?
 timeout configured and          ├─ Yes → return true
 newly entered waiting state?    │   (failure type changed)
 ├─ Yes → return true            └─ No → return false
 └─ No → return false                (same failure, deduped)
```

Thanks to this filter, even if a Pod in CrashLoopBackOff just bumps `restartCount` (same failure type), Reconcile is not invoked again.

---

## Step 3: Failure Detection — detectPodFailure

Events that pass the filter enter the Work Queue, and a worker goroutine calls `Reconcile()`. Inside Reconcile, `detectPodFailure()` decides whether the Pod is in an abnormal state.

### Whitelist-based Detection Philosophy

The previous approach was a **blacklist**: enumerating known abnormal states one by one (CrashLoopBackOff, OOMKilled, etc.). When Kubernetes added a new reason, the code had to be updated.

The current approach is a **whitelist** — "if it isn't normal, it's abnormal":

```go
// Normal waiting reasons (allow only these; treat everything else as a failure)
var normalWaitingReasons = map[string]bool{
    "ContainerCreating": true,   // container being created (normal)
    "PodInitializing":   true,   // init container running (normal)
}
```

If Kubernetes adds new abnormal reasons in the future, they are detected automatically without code changes.

### Five Detection Layers

Detection iterates five layers in priority order. The first matching layer returns immediately:

```
Layer 1: Pod Status Reason ─────── Evicted, DeadlineExceeded
         (root-cause first)         When a Pod is evicted or has timed out
                │
Layer 2: Container Waiting ─────── CrashLoopBackOff, ImagePullBackOff,
         (whitelist-based)          ErrImagePull, CreateContainerConfigError, ...
                │                  + ContainerCreating → timeout-eligible
                │
Layer 3: Container Terminated ──── OOMKilled, Error, NonZeroExit
         (exit-code based)          When exit code != 0
                │
Layer 4: Pod Phase ─────────────── PodFailed, PodUnknown
         (Phase status)
                │
Layer 5: Pod Conditions ────────── Unschedulable
         (scheduling condition)     PodScheduled=False
```

**Rationale for the layer order:**
- Layer 1 has top priority: an evicted Pod also has terminated containers, but eviction is the root cause.
- Layer 2 > Layer 3: a Waiting state (CrashLoopBackOff) reflects the current state more accurately than Terminated (OOMKilled).
- Layers 4–5: Pod-level states are less specific than container-level signals, so they come last.

### Init Container Handling

Init containers and regular containers are both inspected in Layers 2 and 3. Failures detected on an init container have `IsInitContainer: true` set.

### Timeout-Eligible States

Some states may be normal initially but indicate trouble if they persist. These are called **timeout-eligible states** and are represented by `RequiresTimeout: true` in `DetectionResult`. The operator waits for `FailureGracePeriod`; if the state is not resolved by then, it is promoted to a failure.

Current timeout-eligible states:

| State | Detection Layer | Promoted Failure Type | Description |
|-------|-----------------|------------------------|-------------|
| `ContainerCreating` | Layer 2 (Container Waiting) | `ContainerCreatingTimeout` | An image pull may be in progress |
| `Unschedulable` | Layer 5 (Pod Conditions) | `UnschedulableTimeout` | The cluster autoscaler may be adding nodes |

```
Timeout-eligible state detected
    │
    ├─ elapsed < FailureGracePeriod
    │   → schedule recheck via RequeueAfter: FailureRecheckInterval
    │
    └─ elapsed >= FailureGracePeriod
        → promote to "{Reason}Timeout" failure and process
```

Settings:
- `FAILURE_GRACE_PERIOD`: timeout grace period (default: 3 minutes). Setting `0` disables timeout-based detection.
- `FAILURE_RECHECK_INTERVAL`: recheck interval (default: 1 minute).

---

## Step 4: Reconcile Processing Flow

Once a failure is detected, Reconcile processes it in this order:

```
Reconcile(ctx, req)
    │
    ├─ 1. Namespace filtering (IsNamespaceWatched)
    │      Check configured watch/exclude namespaces
    │
    ├─ 2. Get Pod (r.Get)
    │      If deleted, ignore via IgnoreNotFound
    │
    ├─ 3. Duplicate-processing check (isAlreadyProcessed)
    │      Annotation-based TTL check
    │
    ├─ 4. Failure detection (detectPodFailure)
    │      Whitelist-based 5-layer detection
    │
    ├─ 5. Timeout handling
    │      ContainerCreating/Unschedulable → RequeueAfter or promote
    │
    ├─ 6. Data collection (buildCollectedData)
    │      ├─ Pod manifest (kubectl get pod -o yaml)
    │      ├─ Pod describe (kubectl describe pod)
    │      ├─ Container logs (current + previous)
    │      ├─ Kubernetes Events
    │      └─ Node logs via SSM (kubelet, containerd, dmesg, ipamd, networking, disk/inode/mem, etc.)
    │
    ├─ 7. Output
    │      ├─ Upload to CloudWatch Logs (optional)
    │      ├─ Upload to S3 (optional)
    │      └─ Send Webhook (optional)
    │
    └─ 8. Mark as processed (markAsProcessed)
           Add annotations on the Pod:
           - devops-agent.io/processed: "true"
           - devops-agent.io/processed-at: <RFC3339 timestamp>
           - devops-agent.io/failure-type: <failure type>
```

---

## Step 5: Duplicate Processing Prevention — isAlreadyProcessed

To prevent the same Pod failure from being processed multiple times, an annotation-based duplicate check is used:

```
Does the Pod have the devops-agent.io/processed-at annotation?
    │
    ├─ No  → not processed; continue Reconcile
    │
    └─ Yes → parse the processed timestamp
                │
                ├─ Within TTL → already processed; skip
                └─ TTL exceeded → reprocessing allowed (a new failure may have occurred)
```

This mechanism, combined with `hasFailureStateChanged`, provides defense-in-depth:
- **First line of defense**: EventFilter blocks events whose failure state hasn't changed.
- **Second line of defense**: After entering Reconcile, the annotation skips Pods that have already been processed.

---

## Step 6: Severity Determination — DetermineSeverity

Severity is determined from the failure Type via a data-driven mapping. The mapping lives in `collector/severity.go` and is shared by both the controller and the output packages:

| Severity | Failure Type |
|----------|--------------|
| **CRITICAL** | OOMKilled |
| **HIGH** | CrashLoopBackOff, Evicted, ImagePullBackOff, ErrImagePull |
| **MEDIUM** | CreateContainerConfigError, CreateContainerError, InvalidImageName, ErrImageNeverPull, RunContainerError, PostStartHookError, PreCreateHookError, PreStartHookError, Error, NonZeroExit, PodFailed, PodUnknown, Unschedulable, UnschedulableTimeout, DeadlineExceeded |
| **LOW** | ContainerCreatingTimeout, unregistered types (default) |

---

## Step 7: Data Collection and Output

### Collected Items

| Item | Method | Description |
|------|--------|-------------|
| Pod Manifest | Kubernetes API (get -o yaml) | Full Pod spec |
| Pod Describe | Kubernetes API (describe) | Detailed status |
| Container Logs | Kubernetes API (logs) | Current + previous logs |
| Events | Kubernetes API (events) | List of Pod-related events |
| Node Logs | AWS SSM SendCommand | kubelet, containerd, dmesg, ipamd, ipamd-introspection, networking, disk/inode/mem usage |

### Output Paths

Three outputs can be enabled independently based on configuration:

```
CollectedData
    │
    ├─▶ CloudWatch Logs (when CLOUDWATCH_LOG_GROUP is set)
    │     Upload structured JSON to the configured log group/stream
    │
    ├─▶ S3 (when S3_BUCKET is set)
    │     Upload files under incidents/<timestamp>/<namespace>/<pod-name>/
    │     - collected-data.json, failure-info.json
    │     - pod-manifest.yaml, pod-describe.yaml
    │     - logs/<container>.log
    │     - node-logs/kubelet.log, containerd.log, dmesg.log,
    │       ipamd.log, ipamd-introspection.log, networking.txt,
    │       disk-usage.txt, inode-usage.txt, mem-usage.txt
    │
    └─▶ Webhook (when WEBHOOK_URL is set)
          Send an incident payload that includes the S3 URL
          Authenticated with HMAC-SHA256 signing
```

---

## Full Sequence Diagram

```
K8s API Server          controller-runtime           PodReconciler
     │                        │                           │
     │  Pod Update event       │                          │
     │───────────────────────▶│                           │
     │                        │  EventFilter              │
     │                        │  hasFailureStateChanged() │
     │                        │──────┐                    │
     │                        │      │ check failure-     │
     │                        │      │ state change       │
     │                        │◀─────┘                    │
     │                        │                           │
     │                        │  [no change] → ignore     │
     │                        │                           │
     │                        │  [changed] → enqueue      │
     │                        │                           │
     │                        │  Worker dequeues          │
     │                        │──────────────────────────▶│
     │                        │                           │ Reconcile()
     │                        │                           │──┐
     │                        │                           │  │ 1. Namespace check
     │                        │                           │  │ 2. Duplicate check
     │◀──────────────────────────────────────────────────│  │ 3. Get Pod
     │  Get Pod (GET)         │                           │  │
     │───────────────────────────────────────────────────▶│  │
     │                        │                           │  │ 4. detectPodFailure()
     │                        │                           │  │ 5. Data collection
     │◀──────────────────────────────────────────────────│  │    (logs, events, ...)
     │  Get Logs/Events       │                           │  │
     │───────────────────────────────────────────────────▶│  │
     │                        │                           │  │ 6. Output
     │                        │                           │  │    (CW, S3, Webhook)
     │                        │                           │  │
     │◀──────────────────────────────────────────────────│  │ 7. Annotation patch
     │  Patch (mark processed)│                           │  │    (markAsProcessed)
     │───────────────────────────────────────────────────▶│◀─┘
     │                        │                           │
```

---

## RequeueAfter Mechanism

Reconcile can schedule re-execution by returning `ctrl.Result`:

| Return value | Meaning |
|--------------|---------|
| `ctrl.Result{}` | Completed normally, no re-execution |
| `ctrl.Result{RequeueAfter: 30s}` | Re-run Reconcile against the same Pod after 30 seconds |
| `ctrl.Result{}, err` | Error occurred; re-run with exponential backoff |

Detection of timeout-eligible states (ContainerCreating, Unschedulable) leverages this:
1. Detect a timeout-eligible state → return `RequeueAfter: FailureRecheckInterval`
2. Reconcile is invoked again at the recheck time
3. If the state has been resolved → exit normally (not a failure)
4. If still in the same state → check elapsed time
5. If `FailureGracePeriod` is exceeded → promote to a `{Reason}Timeout` failure and process it

---

## Package Dependency Structure

To prevent circular dependencies, packages depend in only one direction:

```
cmd/main.go
    │
    ├──▶ internal/controller    (Pod Watch, failure detection, Reconcile)
    │        │
    │        ├──▶ internal/collector   (data structures, log collection, SSM, severity)
    │        │
    │        └──▶ internal/output      (Webhook, S3, CloudWatch)
    │                  │
    │                  └──▶ internal/collector   (data structures, severity reference)
    │
    └──▶ internal/config        (environment-variable config)
```

Why `DetermineSeverity()` lives in the `collector` package: both `controller` and `output` need the severity mapping, so placing it in `collector` (accessible from both) prevents a circular dependency.

---

## Scenario Walkthroughs

### Scenario 1: Common Failure Detection (CrashLoopBackOff)

A Pod's container repeatedly fails to restart and ends up in CrashLoopBackOff.

```
1. Kubelet fails to restart the container → Pod state updated to CrashLoopBackOff
2. The API Server emits a Pod Update event

3. EventFilter (hasFailureStateChanged)
   ├─ oldPod: Running (healthy)
   ├─ newPod: Waiting/CrashLoopBackOff (failure)
   └─ no failure → has failure = state change → ✅ enqueue

4. Reconcile() entry
   ├─ Namespace check → watched
   ├─ isAlreadyProcessed → false (not yet processed)
   └─ detectPodFailure()
       ├─ Layer 1: Pod Status Reason → no match
       ├─ Layer 2: Container Waiting → ⚡ CrashLoopBackOff detected
       │   not in normalWaitingReasons → immediately classified as a failure
       │   FailureInfo{Type: "CrashLoopBackOff", Category: "ContainerWaiting"}
       └─ (skip remaining layers)

5. Timeout handling → RequiresTimeout=false → skip

6. Data collection (buildCollectedData)
   ├─ Pod manifest (YAML)
   ├─ Pod describe (status detail)
   ├─ Container logs (current + previous)
   ├─ Kubernetes Events
   └─ Node logs via SSM (when enabled)

7. Output
   ├─ Upload to CloudWatch Logs
   ├─ Upload to S3
   └─ Send webhook (severity: HIGH)

8. markAsProcessed → add annotations
   devops-agent.io/failure-type: CrashLoopBackOff
```

**If the same CrashLoopBackOff repeats on the same Pod:**
- In EventFilter, both oldPod and newPod are CrashLoopBackOff → same Type → returns `false` → not enqueued
- Even if it were enqueued, isAlreadyProcessed would skip it within TTL

---

### Scenario 2: Pending Pod Detection (Unschedulable)

A Pod cannot be scheduled due to IP exhaustion, insufficient resources, etc. Unschedulable can resolve once the cluster autoscaler adds nodes, so the operator does not classify it as a failure immediately and instead waits for `FailureGracePeriod`.

```
1. Pod create request → Scheduler can't find a suitable node
2. Scheduler updates PodCondition:
   PodScheduled = False, Reason = "Unschedulable"
   Message = "0/3 nodes are available: 3 Too many pods."

3. EventFilter (hasFailureStateChanged)
   ├─ oldPod: no failure, RequiresTimeout=false
   ├─ newPod: no failure, RequiresTimeout=true (detected at Layer 5)
   └─ FailureGracePeriod > 0 and newly entered timeout-eligible state → ✅ enqueue

4. Reconcile() first entry
   ├─ detectPodFailure()
   │   ├─ Layer 1–4: no match
   │   └─ Layer 5: PodScheduled=False, Reason=Unschedulable
   │       in timeoutConditionReasons → RequiresTimeout=true
   │       DetectionResult{Failure: nil, RequiresTimeout: true,
   │                       WaitingReason: "Unschedulable",
   │                       Category: "PodCondition",
   │                       Message: "0/3 nodes are available: ..."}
   │
   ├─ Timeout handling
   │   elapsed (30s) < FailureGracePeriod (3m)
   │   → still waiting
   └─ return RequeueAfter: FailureRecheckInterval (1m)

5. Reconcile() second entry (1 minute later, via Requeue)
   ├─ detectPodFailure() → still RequiresTimeout=true
   ├─ elapsed (1m30s) < FailureGracePeriod (3m)
   └─ return RequeueAfter: FailureRecheckInterval (1m)

   ※ If the autoscaler adds nodes and the Pod gets scheduled at this point:
     detectPodFailure() → Failure=nil, RequiresTimeout=false
     → exit normally (not a failure)

6. Reconcile() fourth entry (>3 minutes elapsed, still Unschedulable)
   ├─ detectPodFailure() → RequiresTimeout=true
   ├─ Timeout handling
   │   elapsed (3m30s) >= FailureGracePeriod (3m)
   │   → ⚡ promoted to a failure
   │   FailureInfo{
   │     Type: "UnschedulableTimeout",
   │     Category: "PodCondition",
   │     Message: "Pod stuck in Unschedulable for 3m30s (threshold: 3m0s):
   │              0/3 nodes are available: 3 Too many pods."
   │   }
   │
   ├─ Data collection
   │   ├─ Pod manifest, describe, events
   │   ├─ Container logs (may be absent — containers haven't started)
   │   └─ Node logs → NodeName empty, so SSM collection auto-skips
   │
   ├─ Output (severity: MEDIUM)
   └─ markAsProcessed
```

**Key points:**
- The Pending phase by itself is not a trigger. The Scheduler must set `PodScheduled=False, Reason=Unschedulable` for detection.
- Wait for `FailureGracePeriod` (default 3 minutes) to account for autoscaler time.
- Because NodeName is empty, SSM node-log collection is automatically skipped.

---

### Scenario 3: Stuck ContainerCreating Detection

The container gets stuck in ContainerCreating due to slow image pulls, volume-mount failures, etc. ContainerCreating is part of normal startup, so the operator only classifies it as a failure after waiting `FailureGracePeriod`.

```
1. Pod is scheduled to a node → Kubelet attempts to start the container
2. Image pull is in progress, or volume mount is pending
   → Container state: Waiting, Reason: "ContainerCreating"

3. EventFilter (hasFailureStateChanged)
   ├─ oldPod: no failure, RequiresTimeout=false
   ├─ newPod: no failure, RequiresTimeout=true (detected at Layer 2)
   └─ FailureGracePeriod > 0 and newly entered timeout-eligible state → ✅ enqueue

4. Reconcile() first entry
   ├─ detectPodFailure()
   │   ├─ Layer 1: no match
   │   └─ Layer 2: Container Waiting → Reason="ContainerCreating"
   │       in normalWaitingReasons → not a failure
   │       in timeoutWaitingReasons → RequiresTimeout=true
   │       DetectionResult{Failure: nil, RequiresTimeout: true,
   │                       WaitingReason: "ContainerCreating",
   │                       Container: "my-app",
   │                       Category: "ContainerWaiting"}
   │
   ├─ Timeout handling
   │   elapsed (20s) < FailureGracePeriod (3m)
   │   → still waiting
   └─ return RequeueAfter: FailureRecheckInterval (1m)

5. Reconcile() second entry (1 minute later)
   ├─ detectPodFailure() → still RequiresTimeout=true
   ├─ elapsed (1m20s) < FailureGracePeriod (3m)
   └─ return RequeueAfter: FailureRecheckInterval (1m)

   ※ If the image pull completes and the container moves to Running here:
     detectPodFailure() → Failure=nil, RequiresTimeout=false
     → exit normally (not a failure)

6. Reconcile() fourth entry (>3 minutes elapsed, still ContainerCreating)
   ├─ detectPodFailure() → RequiresTimeout=true
   ├─ Timeout handling
   │   elapsed (3m20s) >= FailureGracePeriod (3m)
   │   → ⚡ promoted to a failure
   │   FailureInfo{
   │     Type: "ContainerCreatingTimeout",
   │     Category: "ContainerWaiting",
   │     Container: "my-app",
   │     Message: "Pod stuck in ContainerCreating for 3m20s (threshold: 3m0s)"
   │   }
   │
   ├─ Data collection
   │   ├─ Pod manifest, describe, events
   │   ├─ Container logs (may be absent — containers haven't started)
   │   └─ Node logs via SSM (collectible since NodeName exists)
   │       kubelet, containerd, dmesg, ipamd, ipamd-introspection, networking, disk/inode/mem usage
   │
   ├─ Output (severity: LOW)
   └─ markAsProcessed
```

**Key points:**
- ContainerCreating is in the `normalWaitingReasons` whitelist, so it isn't classified as a failure immediately.
- It is also in `timeoutWaitingReasons`, making it subject to the timeout watcher.
- Unlike Unschedulable, NodeName is set, so SSM node-log collection is possible.
- Common reasons ContainerCreating doesn't resolve: nonexistent image tag, PVC binding failure, missing Secret/ConfigMap, etc. In those cases, the state usually transitions from ContainerCreating to ImagePullBackOff (or similar) and is detected immediately at Layer 2.

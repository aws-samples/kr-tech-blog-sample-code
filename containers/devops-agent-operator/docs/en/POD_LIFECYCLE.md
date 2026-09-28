> **English** | [한국어](../ko/POD_LIFECYCLE.md)

# Pod Lifecycle Reference

A reference document summarizing the per-stage behavior of a Kubernetes Pod's lifecycle and the errors that can occur at each stage.

---

## 1. Pod Lifecycle Order

### 1-1. Pending Phase

The preparation stage between Pod creation and the start of the actual containers.

| Order | Stage | Performed by | `pod.status.phase` | `kubectl get pod` STATUS | Description |
|:----:|------|-----------|---------------------|--------------------------|------|
| 1 | **Scheduling** | kube-scheduler | `Pending` | `Pending` | Selects a suitable node based on resource requests, nodeSelector, affinity, and taints/tolerations |
| 2 | **Image Pull** | kubelet | `Pending` | `ContainerCreating` | Pulls the container image from the registry (cache usage decided by `imagePullPolicy`) |
| 3 | **Volume Mount** | kubelet | `Pending` | `ContainerCreating` | Attaches volumes (PV/PVC, ConfigMap, Secret, etc.) to the node and mounts them into container paths |
| 4 | **Init Containers** | kubelet | `Pending` | `Init:0/N` | Runs defined init containers sequentially; each must exit 0 before proceeding |
| 5 | **Container Creating** | kubelet + container runtime | `Pending` | `ContainerCreating` | Creates the sandbox, allocates cgroups, sets up the network namespace, and starts the container process |

### 1-2. Running Phase

All preparations are complete and the containers are running.

| Order | Stage | Performed by | `pod.status.phase` | `kubectl get pod` STATUS | Description |
|:----:|------|-----------|---------------------|--------------------------|------|
| 6 | **Running** | kubelet | `Running` | `Running` | All containers are running; Liveness/Readiness/Startup probes are executed |
| 7 | **Restart (optional)** | kubelet | `Running` | e.g. `CrashLoopBackOff` | Containers are restarted on abnormal exits according to `restartPolicy` (Always, OnFailure) |

### 1-3. Termination Phase

The terminal states where the Pod is no longer running.

| Order | Stage | Performed by | `pod.status.phase` | `kubectl get pod` STATUS | Description |
|:----:|------|-----------|---------------------|--------------------------|------|
| 8-a | **Succeeded** | kubelet | `Succeeded` | `Completed` | All containers exited with code 0 (typically Job/CronJob) |
| 8-b | **Failed** | kubelet | `Failed` | `Error` | A container exited abnormally + `restartPolicy: Never` |
| 8-c | **Unknown** | kube-apiserver | `Unknown` | `Unknown` | Cannot communicate with kubelet (node failure, network partition) |
| 8-d | **Terminating** | kubelet | `Running`* | `Terminating` | Delete request -> preStop hook -> SIGTERM -> gracePeriod -> SIGKILL |

> \* `Terminating` is not an actual `pod.status.phase` value. Once `deletionTimestamp` is set, kubectl displays the STATUS as `Terminating`, while the API-side phase keeps its prior value (e.g., `Running`) until deletion completes.

---

## 2. Errors That Can Occur at Each Stage

### 2-1. Pending Phase Errors

#### Scheduling Failures

| `kubectl get pod` STATUS | Cause | How to verify |
|--------------------------|-------|---------------|
| `Pending` | Insufficient resources (CPU/Memory) | `kubectl describe pod` -> `FailedScheduling` in Events |
| `Pending` | No toleration for taints | Same |
| `Pending` | No node matches nodeSelector/affinity | Same |

#### Image Pull Failures

| `kubectl get pod` STATUS | Cause | How to verify |
|--------------------------|-------|---------------|
| `ErrImagePull` | Wrong image name/tag, registry not reachable | `Failed to pull image` in Events |
| `ImagePullBackOff` | Repeated failures entered BackOff | Same |

#### Volume Mount Failures

| `kubectl get pod` STATUS | Cause | How to verify |
|--------------------------|-------|---------------|
| `ContainerCreating` (prolonged) | PVC is not Bound | `kubectl get pvc`, `FailedMount` in Events |
| `ContainerCreating` (prolonged) | Missing StorageClass or provisioner error | Same |
| `ContainerCreating` (prolonged) | Missing Secret/ConfigMap | `MountVolume.SetUp failed` in Events |

#### Init Container Failures

| `kubectl get pod` STATUS | Cause | How to verify |
|--------------------------|-------|---------------|
| `Init:Error` | Init container exited abnormally (exit != 0) | `kubectl logs <pod> -c <init-container>` |
| `Init:CrashLoopBackOff` | Init container fails repeatedly | Same |
| `Init:OOMKilled` | Init container exceeded its memory limit | `kubectl describe pod` -> lastState |
| `Init:ImagePullBackOff` | Init container image pull failed | Check Events |

#### Container Creating Failures

| `kubectl get pod` STATUS | Cause | How to verify |
|--------------------------|-------|---------------|
| `CreateContainerError` | Sandbox creation failure, runtime error | `Failed to create container` in Events |
| `CreateContainerConfigError` | References a nonexistent ConfigMap/Secret | Check Events |
| `ContainerCreating` (prolonged) | CNI plugin error (e.g., IP allocation failed) | `NetworkNotReady`, etc. in Events |

### 2-2. Running Phase Errors

| Situation | `kubectl get pod` STATUS | `pod.status.phase` | Cause | How to verify |
|-----------|--------------------------|---------------------|-------|---------------|
| OOMKilled | `OOMKilled` -> `CrashLoopBackOff` | `Running` | Container exceeded memory limit (exit 137) | `kubectl describe pod` -> `lastState.terminated.reason` |
| Error | `Error` -> `CrashLoopBackOff` | `Running` | Application error caused abnormal exit (exit != 0) | `kubectl logs <pod> --previous` |
| Liveness Probe failure | `Running` (restartCount increases) | `Running` | Consecutive Liveness Probe failures restart the container | `kubectl describe pod` -> `Unhealthy` in Events |
| Eviction | `Evicted` | `Failed` | Node disk/memory pressure | `kubectl describe pod` -> `status.reason: Evicted` |
| Preemption | `Terminating` -> deleted | - | Preempted by a higher-PriorityClass Pod | `Preempted` in Events |

### 2-3. Termination Phase Errors

| Situation | `kubectl get pod` STATUS | Cause | How to verify |
|-----------|--------------------------|-------|---------------|
| Terminating hangs for a long time | `Terminating` | preStop hook delay, process ignores SIGTERM | `kubectl describe pod` -> check `deletionTimestamp` |
| Force deletion required | `Terminating` | Finalizer not released, kubelet unresponsive due to node failure | `kubectl delete pod --force --grace-period=0` |
| Persistent Unknown | `Unknown` | Node NotReady, network partition | `kubectl get nodes`, `kubectl describe node` |

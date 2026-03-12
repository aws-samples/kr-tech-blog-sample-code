# Pod Lifecycle Reference

Kubernetes Pod의 생명주기 단계별 동작과 각 단계에서 발생할 수 있는 오류를 정리한 참고 문서입니다.

---

## 1. Pod Lifecycle 순서

### 1-1. Pending Phase

Pod이 생성된 후 실제 컨테이너가 실행되기 전까지의 준비 단계입니다.

| 순서 | 단계 | 수행 주체 | `pod.status.phase` | `kubectl get pod` STATUS | 설명 |
|:----:|------|-----------|---------------------|--------------------------|------|
| 1 | **Scheduling** | kube-scheduler | `Pending` | `Pending` | 리소스 요청량, nodeSelector, affinity, taint/toleration을 고려하여 적합한 노드 선택 |
| 2 | **Image Pull** | kubelet | `Pending` | `ContainerCreating` | 컨테이너 이미지를 레지스트리에서 다운로드 (`imagePullPolicy`에 따라 캐시 사용 여부 결정) |
| 3 | **Volume Mount** | kubelet | `Pending` | `ContainerCreating` | PV/PVC, ConfigMap, Secret 등 볼륨을 노드에 attach 후 컨테이너 경로에 mount |
| 4 | **Init Containers** | kubelet | `Pending` | `Init:0/N` | 정의된 Init 컨테이너를 순차 실행, 모두 exit 0으로 종료해야 다음 단계 진행 |
| 5 | **Container Creating** | kubelet + container runtime | `Pending` | `ContainerCreating` | sandbox 생성, cgroup 할당, 네트워크 네임스페이스 설정, 컨테이너 프로세스 시작 |

### 1-2. Running Phase

모든 준비가 완료되어 컨테이너가 실행 중인 단계입니다.

| 순서 | 단계 | 수행 주체 | `pod.status.phase` | `kubectl get pod` STATUS | 설명 |
|:----:|------|-----------|---------------------|--------------------------|------|
| 6 | **Running** | kubelet | `Running` | `Running` | 모든 컨테이너 실행 중, Liveness/Readiness/Startup Probe 수행 |
| 7 | **재시작 (선택)** | kubelet | `Running` | `CrashLoopBackOff` 등 | 컨테이너 비정상 종료 시 `restartPolicy`에 따라 재시작 (Always, OnFailure) |

### 1-3. 종료 Phase

Pod이 더 이상 실행되지 않는 최종 상태입니다.

| 순서 | 단계 | 수행 주체 | `pod.status.phase` | `kubectl get pod` STATUS | 설명 |
|:----:|------|-----------|---------------------|--------------------------|------|
| 8-a | **Succeeded** | kubelet | `Succeeded` | `Completed` | 모든 컨테이너가 exit 0으로 종료 (주로 Job/CronJob) |
| 8-b | **Failed** | kubelet | `Failed` | `Error` | 컨테이너가 비정상 종료 + `restartPolicy: Never` |
| 8-c | **Unknown** | kube-apiserver | `Unknown` | `Unknown` | kubelet과 통신 불가 (노드 장애, 네트워크 단절) |
| 8-d | **Terminating** | kubelet | `Running`* | `Terminating` | 삭제 요청 -> preStop hook -> SIGTERM -> gracePeriod -> SIGKILL |

> \* `Terminating`은 실제 `pod.status.phase` 값이 아닙니다. `deletionTimestamp`가 설정되면 kubectl이 STATUS를 `Terminating`으로 표시하며, API상 phase는 삭제 완료 전까지 기존 값(`Running` 등)을 유지합니다.

---

## 2. 단계별 발생 가능한 오류

### 2-1. Pending Phase 오류

#### Scheduling 실패

| `kubectl get pod` STATUS | 원인 | 확인 방법 |
|--------------------------|------|-----------|
| `Pending` | 리소스(CPU/Memory) 부족 | `kubectl describe pod` -> Events에 `FailedScheduling` |
| `Pending` | taint에 대한 toleration 없음 | 동일 |
| `Pending` | nodeSelector/affinity 매칭 노드 없음 | 동일 |

#### Image Pull 실패

| `kubectl get pod` STATUS | 원인 | 확인 방법 |
|--------------------------|------|-----------|
| `ErrImagePull` | 이미지 이름/태그 오류, 레지스트리 접근 불가 | Events에 `Failed to pull image` |
| `ImagePullBackOff` | 위 오류가 반복되어 BackOff 진입 | 동일 |

#### Volume Mount 실패

| `kubectl get pod` STATUS | 원인 | 확인 방법 |
|--------------------------|------|-----------|
| `ContainerCreating` (장시간) | PVC가 Bound 상태가 아님 | `kubectl get pvc`, Events에 `FailedMount` |
| `ContainerCreating` (장시간) | StorageClass 없음 또는 provisioner 오류 | 동일 |
| `ContainerCreating` (장시간) | Secret/ConfigMap 미존재 | Events에 `MountVolume.SetUp failed` |

#### Init Container 실패

| `kubectl get pod` STATUS | 원인 | 확인 방법 |
|--------------------------|------|-----------|
| `Init:Error` | Init 컨테이너가 비정상 종료 (exit != 0) | `kubectl logs <pod> -c <init-container>` |
| `Init:CrashLoopBackOff` | Init 컨테이너 반복 실패 | 동일 |
| `Init:OOMKilled` | Init 컨테이너 메모리 limit 초과 | `kubectl describe pod` -> lastState |
| `Init:ImagePullBackOff` | Init 컨테이너 이미지 pull 실패 | Events 확인 |

#### Container Creating 실패

| `kubectl get pod` STATUS | 원인 | 확인 방법 |
|--------------------------|------|-----------|
| `CreateContainerError` | sandbox 생성 실패, runtime 오류 | Events에 `Failed to create container` |
| `CreateContainerConfigError` | 존재하지 않는 ConfigMap/Secret 참조 | Events 확인 |
| `ContainerCreating` (장시간) | CNI 플러그인 오류 (IP 할당 실패 등) | Events에 `NetworkNotReady` 등 |

### 2-2. Running Phase 오류

| 상황 | `kubectl get pod` STATUS | `pod.status.phase` | 원인 | 확인 방법 |
|------|--------------------------|---------------------|------|-----------|
| OOMKilled | `OOMKilled` -> `CrashLoopBackOff` | `Running` | 컨테이너 메모리 limit 초과 (exit 137) | `kubectl describe pod` -> lastState.terminated.reason |
| Error | `Error` -> `CrashLoopBackOff` | `Running` | 애플리케이션 오류로 비정상 종료 (exit != 0) | `kubectl logs <pod> --previous` |
| Liveness Probe 실패 | `Running` (restartCount 증가) | `Running` | Liveness Probe 연속 실패로 컨테이너 재시작 | `kubectl describe pod` -> Events에 `Unhealthy` |
| Eviction | `Evicted` | `Failed` | 노드 디스크/메모리 pressure | `kubectl describe pod` -> status.reason: Evicted |
| Preemption | `Terminating` -> 삭제 | - | 높은 PriorityClass Pod에 의해 선점 | Events에 `Preempted` |

### 2-3. 종료 Phase 오류

| 상황 | `kubectl get pod` STATUS | 원인 | 확인 방법 |
|------|--------------------------|------|-----------|
| Terminating 장시간 대기 | `Terminating` | preStop hook 지연, 프로세스가 SIGTERM 무시 | `kubectl describe pod` -> deletionTimestamp 확인 |
| 강제 삭제 필요 | `Terminating` | finalizer 미해제, 노드 장애로 kubelet 미응답 | `kubectl delete pod --force --grace-period=0` |
| Unknown 지속 | `Unknown` | 노드 NotReady, 네트워크 단절 | `kubectl get nodes`, `kubectl describe node` |

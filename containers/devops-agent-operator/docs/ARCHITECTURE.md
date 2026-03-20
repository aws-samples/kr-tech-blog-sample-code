# DevOps Agent Operator 동작 원리

이 문서는 DevOps Agent Operator가 어떻게 Pod 이상 상태를 감지하고, 트러블슈팅 데이터를 수집하여 외부 시스템으로 전달하는지 전체 흐름을 설명합니다.

---

## 전체 아키텍처

```
┌─────────────────────────────────────────────────────────────────────┐
│                        Kubernetes API Server                        │
│                                                                     │
│  Pod 리소스 변경 시 Informer를 통해 이벤트 전파                         │
└───────────────┬─────────────────────────────────────────────────────┘
                │ List & Watch (Pod)
                ▼
┌─────────────────────────────────────────────────────────────────────┐
│                      controller-runtime Manager                     │
│                                                                     │
│  ┌──────────────┐    ┌──────────────┐    ┌───────────────────────┐  │
│  │   Informer   │───▶│ EventFilter  │───▶│     Work Queue        │  │
│  │  (Pod Watch) │    │ (predicate)  │    │ (NamespacedName 큐)   │  │
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
                          │  1. 네임스페이스 필터링                  │
                          │  2. 중복 처리 확인                      │
                          │  3. 장애 감지 (detectPodFailure)        │
                          │  4. 데이터 수집 (buildCollectedData)    │
                          │  5. 출력 (CloudWatch, S3, Webhook)     │
                          │  6. 처리 완료 마킹                      │
                          └───────────────────────────────────────┘
```

---

## 1단계: 시작 - Manager 초기화

Operator 프로세스가 시작되면 `cmd/main.go`에서 다음 순서로 초기화됩니다.

```
main()
  ├─ ctrl.NewManager()              # controller-runtime Manager 생성
  ├─ config.LoadFromEnv()           # 환경 변수에서 설정 로드
  ├─ collector/output 클라이언트 생성  # LogCollector, SSM, S3, CloudWatch, Webhook
  ├─ PodReconciler{}.SetupWithManager(mgr)   # Controller 등록
  └─ mgr.Start()                    # Manager 시작 → 이벤트 루프 진입
```

`SetupWithManager()`가 핵심 등록 지점입니다:

```go
// internal/controller/pod_controller.go

func (r *PodReconciler) SetupWithManager(mgr ctrl.Manager) error {
    return ctrl.NewControllerManagedBy(mgr).
        For(&corev1.Pod{}).                    // "Pod 리소스를 Watch한다"
        WithEventFilter(predicate.Funcs{...}). // 이벤트 필터 등록
        Complete(r)                            // r = Reconciler 구현체
}
```

이 호출이 수행하는 내부 동작:

| 단계 | 설명 |
|------|------|
| `For(&corev1.Pod{})` | Pod에 대한 SharedInformer 생성. API Server와 List/Watch 연결 수립 |
| `WithEventFilter(...)` | 이벤트를 큐에 넣기 전 필터링 조건 등록 |
| `Complete(r)` | `r`을 Reconciler로 등록. 내부적으로 Worker goroutine 시작 |

`mgr.Start()` 이후 Informer가 API Server와 연결되어 Pod 변경 이벤트를 실시간으로 수신합니다.

---

## 2단계: 이벤트 필터링 - hasFailureStateChanged

Kubernetes 클러스터에서는 Pod가 빈번하게 업데이트됩니다 (readiness probe 결과, label 변경, resource status 업데이트 등). 이 모든 이벤트에 대해 Reconcile을 실행하면 불필요한 부하가 발생합니다.

`WithEventFilter`의 predicate가 이를 방지합니다:

```go
WithEventFilter(predicate.Funcs{
    CreateFunc:  func(e event.CreateEvent) bool  { return false },  // 생성 무시
    UpdateFunc:  func(e event.UpdateEvent) bool  {
        return r.hasFailureStateChanged(oldPod, newPod)             // 장애 상태 변화만 통과
    },
    DeleteFunc:  func(e event.DeleteEvent) bool  { return false },  // 삭제 무시
    GenericFunc: func(e event.GenericEvent) bool { return false },  // 기타 무시
})
```

**Create를 무시하는 이유**: Pod가 처음 생성될 때는 아직 스케줄링/컨테이너 시작 전이므로 장애 상태가 아닙니다. 이후 상태가 변경되면 Update 이벤트로 감지합니다.

### hasFailureStateChanged 판별 로직

```
oldPod와 newPod에 대해 각각 detectPodFailure() 실행
                    │
    ┌───────────────┼───────────────────────┐
    ▼               ▼                       ▼
 둘 다 장애 없음   장애 없음→있음          둘 다 장애 있음
    │               │                       │
    │               └─▶ return true         │
    │                  (새 장애 발생)         │
    │                                       │
    ▼                                       ▼
 ContainerCreating              Type 또는 Container 변경?
 타임아웃 설정 있고               ├─ Yes → return true
 새로 대기 상태 진입?             │   (장애 유형 변화)
 ├─ Yes → return true           └─ No → return false
 └─ No → return false               (동일 장애, 중복 방지)
```

이 필터 덕분에 CrashLoopBackOff 상태의 Pod가 restartCount만 증가해도 (장애 유형 동일) Reconcile이 다시 호출되지 않습니다.

---

## 3단계: 장애 감지 - detectPodFailure

필터를 통과한 이벤트는 Work Queue에 들어가고, Worker goroutine이 `Reconcile()`을 호출합니다. Reconcile 내부에서 `detectPodFailure()`가 Pod의 이상 상태를 판별합니다.

### 화이트리스트 기반 감지 철학

기존 방식은 알려진 이상 상태(CrashLoopBackOff, OOMKilled 등)를 하나씩 나열하는 **블랙리스트** 방식이었습니다. Kubernetes가 새 reason을 추가하면 코드 수정이 필요했습니다.

현재는 **"정상이 아니면 이상"** 이라는 화이트리스트 방식입니다:

```go
// 정상 waiting reason (이것만 허용, 나머지는 전부 장애)
var normalWaitingReasons = map[string]bool{
    "ContainerCreating": true,   // 컨테이너 생성 중 (정상)
    "PodInitializing":   true,   // init container 실행 중 (정상)
}
```

Kubernetes가 미래에 새로운 이상 reason을 추가해도 코드 수정 없이 자동 감지됩니다.

### 5개 감지 레이어

감지는 우선순위 순서로 5개 레이어를 순회합니다. 먼저 매칭된 레이어에서 즉시 반환합니다:

```
Layer 1: Pod Status Reason ─────── Evicted, DeadlineExceeded
         (근본 원인 우선)           Pod가 축출/타임아웃된 경우
                │
Layer 2: Container Waiting ─────── CrashLoopBackOff, ImagePullBackOff,
         (화이트리스트 기반)         ErrImagePull, CreateContainerConfigError, ...
                │                  + ContainerCreating → 타임아웃 대기
                │
Layer 3: Container Terminated ──── OOMKilled, Error, NonZeroExit
         (exit code 기반)           exit code != 0인 경우
                │
Layer 4: Pod Phase ─────────────── PodFailed, PodUnknown
         (Phase 상태)
                │
Layer 5: Pod Conditions ────────── Unschedulable
         (스케줄링 조건)            PodScheduled=False
```

**레이어 순서 근거:**
- Layer 1이 최우선: Evicted Pod는 container terminated도 동반하지만, Eviction이 근본 원인
- Layer 2 > Layer 3: Waiting 상태(CrashLoopBackOff)가 Terminated(OOMKilled)보다 현재 상태를 더 정확히 반영
- Layer 4-5: Pod 레벨 상태는 컨테이너 레벨보다 덜 구체적이므로 후순위

### Init Container 처리

Init container와 regular container 모두 Layer 2, 3에서 검사합니다. Init container에서 감지된 장애는 `IsInitContainer: true` 플래그가 설정됩니다.

### 타임아웃 대기 상태 (Timeout-Eligible States)

일부 상태는 정상일 수 있지만 오래 지속되면 이상입니다. 이러한 상태를 **타임아웃 대기 상태**라 하며, `DetectionResult`의 `RequiresTimeout: true`로 표현됩니다. `FailureGracePeriod` 동안 대기한 뒤, 해결되지 않으면 장애로 승격합니다.

현재 타임아웃 대기 대상:

| 상태 | 감지 레이어 | 승격 장애 유형 | 설명 |
|------|-----------|--------------|------|
| `ContainerCreating` | Layer 2 (Container Waiting) | `ContainerCreatingTimeout` | 이미지 풀 진행 중일 수 있음 |
| `Unschedulable` | Layer 5 (Pod Conditions) | `UnschedulableTimeout` | 클러스터 오토스케일러가 노드를 추가 중일 수 있음 |

```
타임아웃 대기 상태 감지
    │
    ├─ 경과 시간 < FailureGracePeriod
    │   → RequeueAfter: FailureRecheckInterval 로 재확인 예약
    │
    └─ 경과 시간 >= FailureGracePeriod
        → "{Reason}Timeout" 장애로 승격하여 처리
```

설정값:
- `FAILURE_GRACE_PERIOD`: 타임아웃 대기 기간 (기본: 3분). 0으로 설정 시 타임아웃 기반 감지 비활성화
- `FAILURE_RECHECK_INTERVAL`: 재확인 간격 (기본: 1분)

---

## 4단계: Reconcile 처리 흐름

장애가 감지되면 Reconcile 내에서 다음 순서로 처리됩니다:

```
Reconcile(ctx, req)
    │
    ├─ 1. 네임스페이스 필터링 (IsNamespaceWatched)
    │      설정된 watch/exclude 네임스페이스 확인
    │
    ├─ 2. Pod 조회 (r.Get)
    │      삭제된 경우 IgnoreNotFound로 무시
    │
    ├─ 3. 중복 처리 확인 (isAlreadyProcessed)
    │      Annotation 기반 TTL 확인
    │
    ├─ 4. 장애 감지 (detectPodFailure)
    │      화이트리스트 기반 5-레이어 감지
    │
    ├─ 5. 타임아웃 처리
    │      ContainerCreating/Unschedulable → RequeueAfter 또는 승격
    │
    ├─ 6. 데이터 수집 (buildCollectedData)
    │      ├─ Pod manifest (kubectl get pod -o yaml)
    │      ├─ Pod describe (kubectl describe pod)
    │      ├─ Container logs (current + previous)
    │      ├─ Kubernetes Events
    │      └─ Node logs via SSM (kubelet, containerd, dmesg, ipamd, networking, disk/inode/mem 등)
    │
    ├─ 7. 출력
    │      ├─ CloudWatch Logs 업로드 (선택)
    │      ├─ S3 업로드 (선택)
    │      └─ Webhook 전송 (선택)
    │
    └─ 8. 처리 완료 마킹 (markAsProcessed)
           Pod에 Annotation 추가:
           - devops-agent.io/processed: "true"
           - devops-agent.io/processed-at: <RFC3339 timestamp>
           - devops-agent.io/failure-type: <failure type>
```

---

## 5단계: 중복 처리 방지 - isAlreadyProcessed

동일한 Pod 장애가 여러 번 처리되는 것을 방지하기 위해 Annotation 기반 중복 체크를 사용합니다:

```
Pod에 devops-agent.io/processed-at Annotation이 있는가?
    │
    ├─ 없음 → 미처리, Reconcile 진행
    │
    └─ 있음 → 처리 시각 파싱
                │
                ├─ TTL 이내 → 이미 처리됨, 스킵
                └─ TTL 초과 → 재처리 허용 (같은 Pod가 새 장애 발생 가능)
```

이 메커니즘과 `hasFailureStateChanged` 필터가 결합되어 이중 방어를 제공합니다:
- **1차 방어**: EventFilter에서 장애 상태가 변하지 않은 이벤트 차단
- **2차 방어**: Reconcile 진입 후 Annotation으로 이미 처리된 Pod 스킵

---

## 6단계: 심각도 결정 - DetermineSeverity

감지된 장애의 Type에 따라 심각도가 데이터 기반으로 결정됩니다. 이 매핑은 `collector/severity.go`에 정의되어 controller와 output 패키지 양쪽에서 공유합니다:

| 심각도 | 장애 유형 |
|--------|----------|
| **CRITICAL** | OOMKilled |
| **HIGH** | CrashLoopBackOff, Evicted, ImagePullBackOff, ErrImagePull |
| **MEDIUM** | CreateContainerConfigError, CreateContainerError, InvalidImageName, ErrImageNeverPull, RunContainerError, PostStartHookError, PreCreateHookError, PreStartHookError, Error, NonZeroExit, PodFailed, PodUnknown, Unschedulable, UnschedulableTimeout, DeadlineExceeded |
| **LOW** | ContainerCreatingTimeout, 미등록 유형 (기본값) |

---

## 7단계: 데이터 수집 및 출력

### 수집 항목

| 항목 | 수집 방법 | 설명 |
|------|----------|------|
| Pod Manifest | Kubernetes API (get -o yaml) | 전체 Pod spec |
| Pod Describe | Kubernetes API (describe) | 상태 상세 정보 |
| Container Logs | Kubernetes API (logs) | 현재 + 이전(previous) 로그 |
| Events | Kubernetes API (events) | Pod 관련 이벤트 목록 |
| Node Logs | AWS SSM SendCommand | kubelet, containerd, dmesg, ipamd, ipamd-introspection, networking, disk/inode/mem usage |

### 출력 경로

설정에 따라 3개 출력을 독립적으로 사용할 수 있습니다:

```
CollectedData
    │
    ├─▶ CloudWatch Logs (CLOUDWATCH_LOG_GROUP 설정 시)
    │     로그 그룹/스트림에 구조화된 JSON 업로드
    │
    ├─▶ S3 (S3_BUCKET 설정 시)
    │     incidents/<timestamp>/<namespace>/<pod-name>/ 경로에 파일 업로드
    │     - collected-data.json, failure-info.json
    │     - pod-manifest.yaml, pod-describe.yaml
    │     - logs/<container>.log
    │     - node-logs/kubelet.log, containerd.log, dmesg.log,
    │       ipamd.log, ipamd-introspection.log, networking.txt,
    │       disk-usage.txt, inode-usage.txt, mem-usage.txt
    │
    └─▶ Webhook (WEBHOOK_URL 설정 시)
          S3 URL을 포함한 인시던트 페이로드 전송
          HMAC-SHA256 서명으로 인증
```

---

## 전체 시퀀스 다이어그램

```
K8s API Server          controller-runtime           PodReconciler
     │                        │                           │
     │  Pod Update 이벤트      │                           │
     │───────────────────────▶│                           │
     │                        │  EventFilter              │
     │                        │  hasFailureStateChanged()  │
     │                        │──────┐                    │
     │                        │      │ 장애 상태           │
     │                        │      │ 변화 확인           │
     │                        │◀─────┘                    │
     │                        │                           │
     │                        │  [변화 없음] → 무시        │
     │                        │                           │
     │                        │  [변화 있음] → 큐에 추가    │
     │                        │                           │
     │                        │  Worker가 큐에서 꺼냄      │
     │                        │──────────────────────────▶│
     │                        │                           │ Reconcile()
     │                        │                           │──┐
     │                        │                           │  │ 1. 네임스페이스 확인
     │                        │                           │  │ 2. 중복 처리 확인
     │◀──────────────────────────────────────────────────│  │ 3. Pod 조회
     │  Pod 조회 (GET)         │                           │  │
     │───────────────────────────────────────────────────▶│  │
     │                        │                           │  │ 4. detectPodFailure()
     │                        │                           │  │ 5. 데이터 수집
     │◀──────────────────────────────────────────────────│  │    (logs, events, ...)
     │  Logs/Events 조회       │                           │  │
     │───────────────────────────────────────────────────▶│  │
     │                        │                           │  │ 6. 출력
     │                        │                           │  │    (CW, S3, Webhook)
     │                        │                           │  │
     │◀──────────────────────────────────────────────────│  │ 7. Annotation 패치
     │  Patch (processed 마킹) │                           │  │    (markAsProcessed)
     │───────────────────────────────────────────────────▶│◀─┘
     │                        │                           │
```

---

## RequeueAfter 메커니즘

Reconcile은 `ctrl.Result`를 반환하여 재실행을 예약할 수 있습니다:

| 반환값 | 의미 |
|--------|------|
| `ctrl.Result{}` | 정상 완료, 재실행 없음 |
| `ctrl.Result{RequeueAfter: 30s}` | 30초 후 같은 Pod에 대해 Reconcile 재실행 |
| `ctrl.Result{}, err` | 에러 발생, exponential backoff 후 재실행 |

타임아웃 대기 상태(ContainerCreating, Unschedulable) 감지에서 이 메커니즘을 활용합니다:
1. 타임아웃 대기 상태 감지 → `RequeueAfter: FailureRecheckInterval` 반환
2. Recheck 시점에 다시 Reconcile 호출
3. 상태가 해소되었으면 → 정상 종료 (장애 아님)
4. 아직 동일 상태이면 → 경과 시간 확인
5. `FailureGracePeriod` 초과 시 → `{Reason}Timeout` 장애로 승격하여 처리

---

## 패키지 의존성 구조

순환 의존을 방지하기 위해 다음 방향으로만 의존합니다:

```
cmd/main.go
    │
    ├──▶ internal/controller    (Pod Watch, 장애 감지, Reconcile)
    │        │
    │        ├──▶ internal/collector   (데이터 구조, 로그 수집, SSM, 심각도)
    │        │
    │        └──▶ internal/output      (Webhook, S3, CloudWatch)
    │                  │
    │                  └──▶ internal/collector   (데이터 구조, 심각도 참조)
    │
    └──▶ internal/config        (환경 변수 설정)
```

`DetermineSeverity()`를 `collector` 패키지에 배치한 이유: `controller`와 `output` 모두 심각도 매핑이 필요하므로, 양쪽에서 접근 가능한 `collector`에 위치시켜 순환 의존을 방지합니다.

---

## 시나리오별 동작 흐름

### 시나리오 1: 일반 장애 감지 (CrashLoopBackOff)

Pod의 컨테이너가 반복적으로 재시작하여 CrashLoopBackOff 상태가 되는 경우입니다.

```
1. Kubelet이 컨테이너 재시작 실패 → Pod 상태를 CrashLoopBackOff로 업데이트
2. API Server가 Pod Update 이벤트 발생

3. EventFilter (hasFailureStateChanged)
   ├─ oldPod: Running (정상)
   ├─ newPod: Waiting/CrashLoopBackOff (장애)
   └─ 장애 없음 → 장애 있음 = 상태 변화 → ✅ 큐에 추가

4. Reconcile() 진입
   ├─ 네임스페이스 확인 → 감시 대상
   ├─ isAlreadyProcessed → false (미처리)
   └─ detectPodFailure()
       ├─ Layer 1: Pod Status Reason → 해당 없음
       ├─ Layer 2: Container Waiting → ⚡ CrashLoopBackOff 감지
       │   normalWaitingReasons에 없음 → 즉시 장애 판정
       │   FailureInfo{Type: "CrashLoopBackOff", Category: "ContainerWaiting"}
       └─ (이후 레이어 검사 스킵)

5. 타임아웃 처리 → RequiresTimeout=false → 스킵

6. 데이터 수집 (buildCollectedData)
   ├─ Pod manifest (YAML)
   ├─ Pod describe (상태 상세)
   ├─ Container logs (current + previous)
   ├─ Kubernetes Events
   └─ Node logs via SSM (활성화 시)

7. 출력
   ├─ CloudWatch Logs 업로드
   ├─ S3 업로드
   └─ Webhook 전송 (severity: HIGH)

8. markAsProcessed → Annotation 추가
   devops-agent.io/failure-type: CrashLoopBackOff
```

**이후 동일 Pod에서 같은 CrashLoopBackOff가 반복되면:**
- EventFilter에서 oldPod/newPod 모두 CrashLoopBackOff → Type 동일 → `false` 반환 → 큐에 추가되지 않음
- 설령 큐에 들어와도 isAlreadyProcessed에서 TTL 이내로 스킵

---

### 시나리오 2: Pending Pod 감지 (Unschedulable)

IP 고갈, 리소스 부족 등으로 Pod가 스케줄링되지 못하는 경우입니다. Unschedulable은 클러스터 오토스케일러가 노드를 추가하면 해결될 수 있으므로, 즉시 장애로 판정하지 않고 `FailureGracePeriod` 동안 대기합니다.

```
1. Pod 생성 요청 → Scheduler가 적합한 노드를 찾지 못함
2. Scheduler가 PodCondition 업데이트:
   PodScheduled = False, Reason = "Unschedulable"
   Message = "0/3 nodes are available: 3 Too many pods."

3. EventFilter (hasFailureStateChanged)
   ├─ oldPod: 장애 없음, RequiresTimeout=false
   ├─ newPod: 장애 없음, RequiresTimeout=true (Layer 5에서 감지)
   └─ FailureGracePeriod > 0 이고 새로 타임아웃 대기 진입 → ✅ 큐에 추가

4. Reconcile() 1차 진입
   ├─ detectPodFailure()
   │   ├─ Layer 1~4: 해당 없음
   │   └─ Layer 5: PodScheduled=False, Reason=Unschedulable
   │       timeoutConditionReasons에 있음 → RequiresTimeout=true
   │       DetectionResult{Failure: nil, RequiresTimeout: true,
   │                       WaitingReason: "Unschedulable",
   │                       Category: "PodCondition",
   │                       Message: "0/3 nodes are available: ..."}
   │
   ├─ 타임아웃 처리
   │   경과 시간 (30초) < FailureGracePeriod (3분)
   │   → 아직 대기 중
   └─ return RequeueAfter: FailureRecheckInterval (1분)

5. Reconcile() 2차 진입 (1분 후, Requeue에 의해)
   ├─ detectPodFailure() → 여전히 RequiresTimeout=true
   ├─ 경과 시간 (1분 30초) < FailureGracePeriod (3분)
   └─ return RequeueAfter: FailureRecheckInterval (1분)

   ※ 이 시점에 오토스케일러가 노드를 추가하여 Pod가 스케줄되면:
     detectPodFailure() → Failure=nil, RequiresTimeout=false
     → 정상 종료 (장애 아님)

6. Reconcile() 4차 진입 (3분 이상 경과, 여전히 Unschedulable)
   ├─ detectPodFailure() → RequiresTimeout=true
   ├─ 타임아웃 처리
   │   경과 시간 (3분 30초) >= FailureGracePeriod (3분)
   │   → ⚡ 장애로 승격
   │   FailureInfo{
   │     Type: "UnschedulableTimeout",
   │     Category: "PodCondition",
   │     Message: "Pod stuck in Unschedulable for 3m30s (threshold: 3m0s):
   │              0/3 nodes are available: 3 Too many pods."
   │   }
   │
   ├─ 데이터 수집
   │   ├─ Pod manifest, describe, events
   │   ├─ Container logs (없을 수 있음 - 컨테이너 미시작)
   │   └─ Node logs → NodeName이 비어있어 SSM 수집 자동 스킵
   │
   ├─ 출력 (severity: MEDIUM)
   └─ markAsProcessed
```

**핵심 포인트:**
- Pending 상태 자체는 트리거가 아닙니다. Scheduler가 `PodScheduled=False, Reason=Unschedulable` 조건을 설정해야 감지됩니다.
- 오토스케일러 동작 시간을 고려하여 `FailureGracePeriod` (기본 3분) 동안 대기합니다.
- NodeName이 비어있으므로 SSM 노드 로그 수집은 자동으로 스킵됩니다.

---

### 시나리오 3: ContainerCreating 멈춤 감지

이미지 풀 지연, 볼륨 마운트 실패 등으로 컨테이너가 ContainerCreating 상태에서 멈추는 경우입니다. ContainerCreating은 정상적인 컨테이너 시작 과정이므로, `FailureGracePeriod` 동안 대기 후에야 장애로 판정합니다.

```
1. Pod가 노드에 스케줄됨 → Kubelet이 컨테이너 시작 시도
2. 이미지 풀이 진행 중이거나 볼륨 마운트 대기 중
   → 컨테이너 상태: Waiting, Reason: "ContainerCreating"

3. EventFilter (hasFailureStateChanged)
   ├─ oldPod: 장애 없음, RequiresTimeout=false
   ├─ newPod: 장애 없음, RequiresTimeout=true (Layer 2에서 감지)
   └─ FailureGracePeriod > 0 이고 새로 타임아웃 대기 진입 → ✅ 큐에 추가

4. Reconcile() 1차 진입
   ├─ detectPodFailure()
   │   ├─ Layer 1: 해당 없음
   │   └─ Layer 2: Container Waiting → Reason="ContainerCreating"
   │       normalWaitingReasons에 있음 → 장애 아님
   │       timeoutWaitingReasons에 있음 → RequiresTimeout=true
   │       DetectionResult{Failure: nil, RequiresTimeout: true,
   │                       WaitingReason: "ContainerCreating",
   │                       Container: "my-app",
   │                       Category: "ContainerWaiting"}
   │
   ├─ 타임아웃 처리
   │   경과 시간 (20초) < FailureGracePeriod (3분)
   │   → 아직 대기 중
   └─ return RequeueAfter: FailureRecheckInterval (1분)

5. Reconcile() 2차 진입 (1분 후)
   ├─ detectPodFailure() → 여전히 RequiresTimeout=true
   ├─ 경과 시간 (1분 20초) < FailureGracePeriod (3분)
   └─ return RequeueAfter: FailureRecheckInterval (1분)

   ※ 이 시점에 이미지 풀이 완료되어 컨테이너가 Running으로 전환되면:
     detectPodFailure() → Failure=nil, RequiresTimeout=false
     → 정상 종료 (장애 아님)

6. Reconcile() 4차 진입 (3분 이상 경과, 여전히 ContainerCreating)
   ├─ detectPodFailure() → RequiresTimeout=true
   ├─ 타임아웃 처리
   │   경과 시간 (3분 20초) >= FailureGracePeriod (3분)
   │   → ⚡ 장애로 승격
   │   FailureInfo{
   │     Type: "ContainerCreatingTimeout",
   │     Category: "ContainerWaiting",
   │     Container: "my-app",
   │     Message: "Pod stuck in ContainerCreating for 3m20s (threshold: 3m0s)"
   │   }
   │
   ├─ 데이터 수집
   │   ├─ Pod manifest, describe, events
   │   ├─ Container logs (없을 수 있음 - 컨테이너 미시작)
   │   └─ Node logs via SSM (NodeName 존재하므로 수집 가능)
   │       kubelet, containerd, dmesg, ipamd, ipamd-introspection, networking, disk/inode/mem usage
   │
   ├─ 출력 (severity: LOW)
   └─ markAsProcessed
```

**핵심 포인트:**
- ContainerCreating은 `normalWaitingReasons` 화이트리스트에 포함되어 즉시 장애로 판정되지 않습니다.
- 동시에 `timeoutWaitingReasons`에도 포함되어 타임아웃 감시 대상이 됩니다.
- Unschedulable과 달리 NodeName이 존재하므로 SSM 노드 로그 수집이 가능합니다.
- ContainerCreating이 해결되지 않는 일반적 원인: 존재하지 않는 이미지 태그, PVC 바인딩 실패, Secret/ConfigMap 미존재 등. 이 경우 보통 ContainerCreating에서 ImagePullBackOff 등으로 전환되어 Layer 2에서 즉시 감지됩니다.

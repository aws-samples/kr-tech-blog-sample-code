# Self-Managed Agentic AI Platform on Amazon EKS — 설치 가이드

이 문서는 EKS Auto Mode 클러스터에 Agentic AI 플랫폼을 배포하는 전체 과정을 설명합니다.
실제 배포 과정에서 발견한 주의사항과 트러블슈팅 내용을 포함합니다.

## 사전 준비사항

- AWS CLI v2 설치 및 자격 증명 구성
- `kubectl` 설치
- `eksctl` 설치
- Helm 3.x 설치
- HuggingFace 계정 및 Access Token ([https://huggingface.co/settings/tokens](https://huggingface.co/settings/tokens))
- GPU 인스턴스(g5 등) 서비스 할당량 확인

## 프로젝트 구조

```
manifests/
├── ebs-storageclass.yaml      # EBS StorageClass (EKS Auto Mode용)
├── gpu-nodepool.yaml           # Karpenter GPU NodePool
├── bifrost-values.yaml         # Bifrost Helm values
├── bifrost-install.sh          # Bifrost 설치 스크립트
├── vllm-deployment.yaml        # vLLM Deployment + Service
├── langfuse-values.yaml        # Langfuse Helm values
├── langfuse-install.sh         # Langfuse 설치 스크립트
├── demo-app-deployment.yaml    # 데모 앱 Deployment + Service + ConfigMap
app/
├── Dockerfile                  # 데모 앱 Docker 이미지
├── config.py                   # Bifrost/Langfuse 설정
├── state.py                    # LangGraph 상태 정의
├── tracing.py                  # Langfuse 트레이싱
├── workflow.py                 # LangGraph 워크플로우
└── agents/
    ├── orchestrator.py         # 쿼리 분류 에이전트
    ├── rag_agent.py            # RAG 에이전트
    ├── document_agent.py       # 문서 분석 에이전트
    └── evaluation_agent.py     # 응답 평가 에이전트
```

---

## 단계 1: EKS Auto Mode 클러스터 생성

```bash
aws eks update-cluster-config \
 --name $CLUSTER_NAME \
 --compute-config enabled=true \
 --kubernetes-network-config '{"elasticLoadBalancing":{"enabled": true}}' \
 --storage-config '{"blockStorage":{"enabled": true}}'
```

클러스터 생성 후 연결을 확인합니다:

```bash
kubectl get nodes
```

> ⚠️ **EKS Auto Mode 특성:**
> - 기본 노드는 ARM64(Graviton) 인스턴스(c6g, c6gn 등)로 프로비저닝됩니다.
> - VPC CNI, CoreDNS 등 핵심 애드온이 자동 관리됩니다.
> - Karpenter가 내장되어 있어 별도 설치가 필요 없습니다.

---

## 단계 2: EBS StorageClass 생성

EKS Auto Mode에서는 기존 `gp2` StorageClass가 동작하지 않습니다.
`ebs.csi.eks.amazonaws.com` provisioner를 사용하는 StorageClass를 생성해야 합니다.

```bash
kubectl apply -f manifests/ebs-storageclass.yaml
```

검증:

```bash
kubectl get storageclass
# ebs-auto (default) 가 표시되어야 합니다
```

> ⚠️ **트러블슈팅 — PVC Pending:**
> StorageClass가 없거나 default로 설정되지 않으면 StatefulSet의 PVC가 Pending 상태에 머뭅니다.
> `kubectl get pvc -A`로 확인하고, Pending PVC가 있으면 StorageClass가 올바르게 설정됐는지 확인하세요.
> 이미 생성된 Pending PVC는 삭제 후 재생성해야 합니다:
> ```bash
> kubectl delete pvc <pvc-name> -n <namespace>
> # Helm upgrade 또는 StatefulSet 재시작으로 PVC 재생성
> ```

---

## 단계 3: GPU NodePool 생성

GPU 워크로드를 위한 Karpenter NodePool을 생성합니다.

```bash
kubectl apply -f manifests/gpu-nodepool.yaml
```

검증:

```bash
kubectl get nodepool
# gpu-inference-pool 이 Ready 상태여야 합니다
```

> ⚠️ **EKS Auto Mode NodePool 주의사항:**
> - `karpenter.k8s.aws` 그룹이 아닌 `eks.amazonaws.com` 그룹을 사용해야 합니다.
> - NodeClassRef: `group: eks.amazonaws.com`, `kind: NodeClass`, `name: default`
> - GPU 인스턴스 카운트 레이블: `eks.amazonaws.com/instance-gpu-count` (not `karpenter.k8s.aws/instance-gpu-count`)
> - GPU 노드는 워크로드(vLLM 등)가 스케줄링될 때 자동으로 프로비저닝됩니다.

> ⚠️ **GPU Operator 불필요:**
> EKS Auto Mode에서는 NVIDIA GPU Operator를 설치하지 마세요.
> Auto Mode가 GPU 드라이버, Container Toolkit, Device Plugin을 자체 관리합니다.
> GPU Operator를 설치하면 노드의 read-only 파일시스템과 충돌하여
> `nvidia-container-toolkit-daemonset`이 `CreateContainerError`로 실패하고,
> vLLM 컨테이너에서 `nvidia-cdi-hook: no such file or directory` 에러가 발생합니다.

---

## 단계 4: Bifrost AI Gateway 배포

### 4.1 Helm repo 추가

```bash
helm repo add bifrost https://maximhq.github.io/bifrost/helm-charts
helm repo update
```

### 4.2 Bifrost 배포

```bash
kubectl create namespace ai-inference
bash manifests/bifrost-install.sh
```

검증:

```bash
kubectl get po -n ai-inference
# bifrost 팟 3개가 Running 상태여야 합니다
```

### 4.3 vLLM Custom Provider 등록

Bifrost는 `provider/model` 형식으로 모델을 지정합니다. vLLM을 custom provider로 등록하려면
ConfigMap(`bifrost-config`)의 `providers`에 다음을 추가합니다:

```json
"self-hosted-vllm": {
  "keys": [
    {"name": "vllm-key-1", "value": "dummy", "models": ["qwen3-8b"], "weight": 1.0}
  ],
  "network_config": {
    "base_url": "http://vllm.ai-inference.svc.cluster.local:8000",
    "default_request_timeout_in_seconds": 120,
    "max_retries": 1
  },
  "custom_provider_config": {
    "base_provider_type": "openai",
    "allowed_requests": {
      "chat_completion": true,
      "chat_completion_stream": true
    },
    "request_path_overrides": {
      "chat_completion": "/v1/chat/completions",
      "chat_completion_stream": "/v1/chat/completions"
    }
  }
}
```

ConfigMap 적용 후 Bifrost pod를 재시작합니다:

```bash
kubectl apply -f manifests/bifrost-config-patch.yaml
kubectl rollout restart deployment bifrost -n ai-inference
```

검증:

```bash
kubectl port-forward svc/bifrost 8080:8080 -n ai-inference &
curl -s http://localhost:8080/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer test-1234" \
  -d '{"model":"self-hosted-vllm/qwen3-8b","messages":[{"role":"user","content":"Hello"}],"max_tokens":30}'
```

> ⚠️ **Bifrost 모델 이름 형식:**
> Bifrost는 `provider/model` 형식을 요구합니다. `qwen3-8b`가 아닌
> `self-hosted-vllm/qwen3-8b`로 지정해야 합니다.
> 앱 코드의 ConfigMap에서도 이 형식을 사용합니다.

### 4.4 Bedrock Provider 추가

Amazon Bedrock을 통해 Claude 등 고성능 모델을 사용하려면 Bifrost에 Bedrock provider를 추가합니다.

#### AWS credentials 설정

```bash
# AWS credentials Secret 생성
kubectl create secret generic bedrock-credentials \
  --from-literal=aws-access-key-id=$AWS_ACCESS_KEY_ID \
  --from-literal=aws-secret-access-key=$AWS_SECRET_ACCESS_KEY \
  -n ai-inference
```

Bifrost Deployment에 표준 AWS 환경변수를 주입합니다:

```bash
kubectl patch deployment bifrost -n ai-inference --type='json' -p='[
  {"op":"add","path":"/spec/template/spec/containers/0/env/-","value":{"name":"BEDROCK_API_KEY","valueFrom":{"secretKeyRef":{"name":"bedrock-credentials","key":"aws-access-key-id"}}}},
  {"op":"add","path":"/spec/template/spec/containers/0/env/-","value":{"name":"AWS_SECRET_ACCESS_KEY","valueFrom":{"secretKeyRef":{"name":"bedrock-credentials","key":"aws-secret-access-key"}}}},
  {"op":"add","path":"/spec/template/spec/containers/0/env/-","value":{"name":"AWS_ACCESS_KEY_ID","valueFrom":{"secretKeyRef":{"name":"bedrock-credentials","key":"aws-access-key-id"}}}},
  {"op":"add","path":"/spec/template/spec/containers/0/env/-","value":{"name":"AWS_REGION","value":"ap-northeast-2"}}
]'
```

#### Bedrock Provider 등록 (Bifrost UI)

Bifrost v1.4.14에서는 config.json의 `bedrock_key_config`가 런타임에 로드되지 않는 이슈가 있습니다.
Bifrost Web UI(`http://localhost:8080`)에서 직접 등록하는 방식을 사용합니다:

1. 브라우저에서 `http://localhost:8080` 접속
2. Providers → Add Provider → `bedrock` 선택
3. Key 추가:
   - Value(API Key): **비워두기** (Bedrock은 API Key가 아닌 AWS credentials 사용)
   - Authentication: **Explicit Credentials** 선택
   - Access Key / Secret Key / Region 입력
4. Models: `global.anthropic.claude-haiku-4-5-20251001-v1:0` 등 사용할 모델 추가
5. 저장

또는 Bifrost API로 등록할 수 있습니다:

```bash
# 각 Bifrost pod에 대해 실행 (3 replicas인 경우)
for POD in $(kubectl get pods -n ai-inference -l app.kubernetes.io/name=bifrost -o jsonpath='{.items[*].metadata.name}'); do
  kubectl exec -n ai-inference $POD -- wget -q -O - \
    --post-data '{"provider":"bedrock","keys":[{"name":"bedrock-key-1","models":["global.anthropic.claude-haiku-4-5-20251001-v1:0"],"weight":1.0,"bedrock_key_config":{"access_key":"'"$AWS_ACCESS_KEY_ID"'","secret_key":"'"$AWS_SECRET_ACCESS_KEY"'","region":"ap-northeast-2"}}]}' \
    --header 'Content-Type: application/json' \
    http://localhost:8080/api/providers
  echo " → $POD done"
done
```

검증:

```bash
kubectl port-forward svc/bifrost 8080:8080 -n ai-inference &
curl -s http://localhost:8080/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"bedrock/global.anthropic.claude-haiku-4-5-20251001-v1:0","messages":[{"role":"user","content":"안녕하세요"}],"max_tokens":50}'
```

실제 테스트 결과:

```json
{
  "model": "global.anthropic.claude-haiku-4-5-20251001-v1:0",
  "choices": [{"message": {"role": "assistant", "content": "안녕하세요. 반갑습니다!"}}],
  "usage": {"prompt_tokens": 27, "completion_tokens": 81}
}
```

> ⚠️ **Bifrost Bedrock 연동 주의사항:**
>
> - `allow_direct_keys: false`로 설정해야 합니다. `true`이면 OpenAI SDK의 `Authorization: Bearer` 헤더를
>   Bifrost가 Bedrock direct key로 해석하여 `bedrock key config is not provided` 에러가 발생합니다.
> - config.json에 bedrock provider를 넣어도 `bedrock_key_config`가 런타임에 로드되지 않는 v1.4.14 이슈가 있습니다.
>   Bifrost UI 또는 API(`/api/providers`)로 등록하면 config_store(SQLite)에 저장되어 정상 작동합니다.
> - config_store는 emptyDir이므로 pod 재시작 시 초기화됩니다. 재시작 후 API로 재등록이 필요합니다.
>   프로덕션에서는 PVC persistence를 켜거나 initContainer로 자동 등록하는 것을 권장합니다.
>
> **프로덕션 환경에서는** IAM Roles for Service Accounts(IRSA) 또는 EKS Pod Identity를
> 사용하여 AWS credentials를 관리하는 것을 권장합니다.
>
> **Bedrock Inference Profile:**
> Claude Haiku 4.5 등 최신 모델은 on-demand 직접 호출이 지원되지 않으며,
> inference profile ID(`global.anthropic.claude-haiku-4-5-20251001-v1:0`)를 사용해야 합니다.
> `aws bedrock list-inference-profiles --region ap-northeast-2`로 사용 가능한 profile을 확인하세요.

---

## 단계 5: vLLM 추론 서버 배포

### 5.1 HuggingFace 토큰 Secret 생성

vLLM이 HuggingFace에서 모델을 다운로드할 때 토큰을 사용합니다.
Qwen3-8B는 공개 모델이라 토큰 없이도 다운로드 가능하지만,
rate limit 방지와 다른 모델(Llama 등 gated model) 전환을 위해 설정을 권장합니다.

```bash
kubectl create secret generic hf-token \
  --from-literal=token=hf_YourActualHuggingFaceToken \
  -n ai-inference
```

> 토큰은 https://huggingface.co/settings/tokens 에서 생성할 수 있습니다 (Read 권한 필요).

### 5.2 모델 접근 확인

Qwen3-8B는 gated model이 아니므로 별도 접근 승인 없이 바로 사용 가능합니다.
다른 모델(예: Meta Llama 시리즈)을 사용하는 경우 HuggingFace 모델 페이지에서
"Request access"를 클릭하고 승인을 받아야 합니다. 승인 전에 vLLM을 배포하면
`401 Client Error: Access to model is restricted` 에러가 발생합니다.

### 5.3 vLLM 배포

```bash
kubectl apply -f manifests/vllm-deployment.yaml
```

모델 다운로드에 3-5분 소요됩니다. 진행 상황을 확인하세요:

```bash
# 팟 상태 확인
kubectl get po -n ai-inference -l app=vllm

# 모델 로딩 로그 확인
kubectl logs -l app=vllm -n ai-inference --tail=5
```

다음 메시지가 나오면 준비 완료입니다:

```
INFO:     Application startup complete.
INFO:     Uvicorn running on http://0.0.0.0:8000 (Press CTRL+C to quit)
```

> ⚠️ **트러블슈팅 — vLLM 관련 이슈:**
>
> **`enableServiceLinks: false` 설정 이유:**
> Kubernetes는 같은 네임스페이스의 Service 이름으로 환경변수를 자동 생성합니다.
> Service 이름이 `vllm`이면 `VLLM_PORT_8000_TCP`, `VLLM_SERVICE_HOST` 등이 생성되는데,
> vLLM 소프트웨어가 이를 자체 설정으로 인식하려다 경고가 발생합니다.
> `enableServiceLinks: false`로 이 동작을 비활성화합니다.
>
> **Helm chart 대신 직접 Deployment 사용 이유:**
> vLLM Production Stack Helm chart의 router 컴포넌트(`lmcache/lmstack-router`)가
> ARM64 이미지를 제공하지 않습니다. EKS Auto Mode의 기본 노드가 ARM64(Graviton)이므로
> router가 스케줄링되지 않습니다. 직접 Deployment를 사용하면 이 문제를 우회할 수 있습니다.
>
> **`--max-model-len 4096` 설정:**
> g5.2xlarge의 GPU 메모리(24GB)에서 안정적으로 동작하도록 최대 시퀀스 길이를 제한합니다.
> 기본값은 모델의 최대 길이(8192)인데, KV Cache 할당 시 OOM이 발생할 수 있습니다.
>
> **이미지 버전 `v0.17.1` 사용:**
> vLLM v0.17.1은 V1 엔진 기반으로 Qwen3, Llama 4 등 최신 모델을 지원합니다.
> EKS Auto Mode의 Bottlerocket AMI GPU 런타임과 호환됩니다.

---

## 단계 6: Langfuse 관측성 플랫폼 배포

### 6.1 Helm repo 추가

```bash
helm repo add langfuse https://langfuse.github.io/langfuse-k8s
helm repo update
```

### 6.2 Langfuse 배포

```bash
bash manifests/langfuse-install.sh
```

Langfuse는 여러 컴포넌트(ClickHouse, PostgreSQL, Redis, Zookeeper, S3/MinIO, Web, Worker)를
포함하고 있어 전체 기동에 5-10분 소요될 수 있습니다.

```bash
# 팟 상태 확인 (모두 Running이 될 때까지 반복)
kubectl get po -n observability

# PVC 바인딩 확인
kubectl get pvc -n observability
```

모든 팟이 Running이고 PVC가 Bound 상태여야 합니다:

```
langfuse-clickhouse-shard0-0       1/1     Running
langfuse-clickhouse-shard0-1       1/1     Running
langfuse-clickhouse-shard0-2       1/1     Running
langfuse-postgresql-0              1/1     Running
langfuse-redis-primary-0           1/1     Running
langfuse-s3-xxxxx                  1/1     Running
langfuse-web-xxxxx                 1/1     Running
langfuse-worker-xxxxx              1/1     Running
langfuse-zookeeper-0               1/1     Running
langfuse-zookeeper-1               1/1     Running
langfuse-zookeeper-2               1/1     Running
```

> ⚠️ **트러블슈팅 — Langfuse PVC Pending:**
>
> Langfuse Helm chart의 subchart(Redis/Valkey, Zookeeper)는 persistence의 storageClass를
> 직접 노출하지 않는 경우가 있습니다. 이 경우 PVC가 storageClass 없이 생성되어 Pending 상태가 됩니다.
>
> **해결 방법 1 (권장):** `ebs-auto` StorageClass를 default로 설정
> ```bash
> # ebs-storageclass.yaml에 아래 annotation이 포함되어 있는지 확인
> # storageclass.kubernetes.io/is-default-class: "true"
> kubectl apply -f manifests/ebs-storageclass.yaml
> ```
>
> **해결 방법 2:** Pending PVC 삭제 후 재생성
> ```bash
> # Pending PVC 확인
> kubectl get pvc -n observability | grep Pending
>
> # Pending PVC 삭제
> kubectl delete pvc <pvc-name> -n observability
>
> # Helm upgrade로 PVC 재생성
> helm upgrade langfuse langfuse/langfuse -n observability -f manifests/langfuse-values.yaml
> ```
>
> **Web/Worker CrashLoopBackOff:**
> Redis가 아직 Ready가 아닐 때 Web과 Worker가 CrashLoopBackOff에 빠질 수 있습니다.
> Redis가 Running되면 자동으로 복구됩니다. 복구가 안 되면 팟을 수동 삭제하세요:
> ```bash
> kubectl delete po -l app.kubernetes.io/name=langfuse -n observability
> ```

> ⚠️ **트러블슈팅 — Langfuse Helm values 형식:**
>
> Langfuse Helm chart는 특정 형식으로 값을 전달해야 합니다:
> - `nextauth.secret.value` (not `nextauth.secret`)
> - `salt.value` (not `salt`)
> - `encryptionKey.value` (not `encryptionKey`)
> - `postgresql.auth.password` (not `postgresql.password`)
> - `clickhouse.auth.password` (not `clickhouse.password`)
>
> 형식이 틀리면 Helm install 시 다음과 같은 에러가 발생합니다:
> ```
> Error: INSTALLATION FAILED: execution error at (langfuse/templates/worker/deployment.yaml):
> Configuring an existing secret or postgresql.auth.password is required
> ```

---

## 단계 7: 데모 애플리케이션 배포

### 7.1 Docker 이미지 빌드 (CodeBuild)

로컬에 Docker가 없는 경우 AWS CodeBuild를 사용하여 이미지를 빌드합니다.

```bash
# ECR 리포지토리 생성
aws ecr create-repository --repository-name demo-app --region ap-northeast-2

# 소스 코드를 S3에 업로드
zip -r source.zip app/ requirements.txt buildspec.yml
aws s3 cp source.zip s3://demo-app-build-source-<AWS_ACCOUNT_ID>/source.zip

# CodeBuild 프로젝트로 빌드 실행
aws codebuild start-build --project-name demo-app-build
```

> ⚠️ `buildspec.yml`에 ECR 로그인, Docker build, push 단계가 포함되어 있어야 합니다.
> CodeBuild IAM Role에 ECR push 권한이 필요합니다.

### 7.2 Langfuse API 키 Secret 생성

Langfuse Web UI에 접속하여 프로젝트를 생성하고 API 키를 발급받습니다:

```bash
# Langfuse Web UI 포트포워딩
kubectl port-forward svc/langfuse-web 3000:3000 -n observability
# 브라우저에서 http://localhost:3000 접속 → 프로젝트 생성 → API Keys 발급
```

```bash
kubectl create secret generic langfuse-keys \
  --from-literal=secret-key=sk-lf-your-secret-key \
  --from-literal=public-key=pk-lf-your-public-key
```

### 7.3 데모 앱 배포

```bash
kubectl apply -f manifests/demo-app-deployment.yaml
```

### 7.4 데모 앱 테스트

```bash
kubectl port-forward svc/demo-app 8000:8000 &

# 간단한 문의 테스트
curl -s http://localhost:8000/query \
  -H "Content-Type: application/json" \
  -d '{"query": "S3 버킷 생성 방법을 알려주세요"}' | python3 -m json.tool
```

실제 테스트 결과:

```json
{
  "user_query": "S3 버킷 생성 방법을 알려주세요",
  "query_type": "simple",
  "selected_model": "self-hosted-vllm/qwen3-8b",
  "response": "S3 버킷을 생성하려면 ...",
  "evaluation_score": 7.0
}
```

복잡한 문의 테스트 (Bedrock 라우팅):

```bash
curl -s http://localhost:8000/query \
  -H "Content-Type: application/json" \
  -d '{"query": "EKS 클러스터에서 OOM 에러가 발생합니다"}' | python3 -m json.tool
```

```json
{
  "user_query": "EKS 클러스터에서 OOM 에러가 발생합니다",
  "query_type": "complex",
  "selected_model": "bedrock/global.anthropic.claude-haiku-4-5-20251001-v1:0",
  "response": "EKS 클러스터에서 OOM(Out-of-Memory) 에러가 발생했을 때 다음과 같은 방법으로 디버깅할 수 있습니다: 1. 클러스터 및 노드 상태 확인 ...",
  "evaluation_score": 7.0
}
```

> Orchestrator가 쿼리를 `complex`로 분류하면 Bifrost가 자동으로 Bedrock(Claude)으로 라우팅합니다.
> Simple 쿼리는 vLLM(~10s), Complex 쿼리는 Bedrock(~7.5s)으로 처리됩니다.

### 7.5 Langfuse 트레이싱 검증

데모 앱 호출 후 Langfuse에서 트레이스가 기록되는지 확인합니다:

```bash
# Langfuse API로 트레이스 조회
kubectl port-forward svc/langfuse-web 3000:3000 -n observability &

curl -s http://localhost:3000/api/public/traces?limit=1 \
  -u "pk-lf-your-public-key:sk-lf-your-secret-key" | python3 -m json.tool
```

실제 확인된 트레이스 정보:

| 항목 | 값 |
|------|-----|
| Trace name | `customer_support` |
| Tags | `["eks-demo", "support"]` |
| Metadata | `{"product": "aws-support"}` |
| Observations | 4개 (orchestrator, rag_agent/document_agent, evaluation_agent, customer_support) |
| SDK | `langfuse-sdk v4.0.0` (OpenTelemetry) |

> 앱 코드의 모든 에이전트에 `@observe` 데코레이터가 적용되어 있어,
> 각 에이전트의 입출력과 실행 시간이 자동으로 Langfuse에 기록됩니다.
> `propagate_attributes()`로 trace_name, tags, metadata가 모든 하위 span에 전파됩니다.

---

## 단계 8: 로컬 데모 실행 (LangGraph + vLLM + Langfuse)

클러스터에 배포된 vLLM과 Langfuse를 로컬에서 직접 호출하여 멀티 에이전트 워크플로우를 테스트합니다.

### 8.1 Python 환경 설정

```bash
python3 -m venv .venv
source .venv/bin/activate

# venv의 pip을 직접 사용 (시스템 pip alias 우회)
.venv/bin/pip install langchain_openai langgraph langfuse python-dotenv
```

> ⚠️ **macOS에서 `externally-managed-environment` 에러:**
> Homebrew Python은 시스템 패키지 보호를 위해 pip install을 차단합니다.
> 반드시 venv를 생성하고, `pip`이 alias로 시스템 pip을 가리키는 경우
> `.venv/bin/pip`으로 직접 호출하세요.

> ⚠️ **Python 3.14 호환성:**
> Python 3.14에서는 Pydantic v1 호환성 문제로 일부 경고가 발생합니다.
> Langfuse SDK v2는 Python 3.14에서 import 에러가 발생하므로 v4를 사용하세요.
> 안정적인 환경을 원하면 Python 3.12 또는 3.13을 권장합니다.

### 8.2 환경변수 설정

`.env` 파일을 생성하여 환경변수를 관리합니다 (`.gitignore`에 추가 권장):

```bash
# .env
LANGFUSE_SECRET_KEY=sk-lf-your-secret-key
LANGFUSE_PUBLIC_KEY=pk-lf-your-public-key
LANGFUSE_BASE_URL=http://localhost:3000
VLLM_URL=http://localhost:8000/v1
```

Langfuse API 키는 Langfuse Web UI에서 발급받습니다:
1. `http://localhost:3000` 접속
2. 계정 생성 → 프로젝트 생성
3. Settings → API Keys에서 Public Key / Secret Key 복사

### 8.3 Port-forward 실행

```bash
kubectl port-forward svc/vllm 8000:8000 -n ai-inference &
kubectl port-forward svc/langfuse-web 3000:3000 -n observability &
```

### 8.4 데모 실행

```bash
.venv/bin/python demo.py
```

정상 실행 시 3개 테스트 쿼리(simple, complex, document)가 순차적으로 처리되며,
각 쿼리의 분류 결과, 선택된 모델, 평가 점수, 응답이 출력됩니다.

```
======================================================================
🤖 Agentic AI Platform Demo — LangGraph + vLLM + Langfuse
======================================================================
   Langfuse 트레이싱: ✅ (http://localhost:3000)

📝 문의: S3 버킷 생성 방법을 알려주세요
   분류: simple
   모델: qwen3-8b
   평가: 7.0/10
   시간: 8.0s
```

실행 후 Langfuse 대시보드(`http://localhost:3000`)의 Traces 탭에서
`customer_support` 트레이스와 각 에이전트의 span을 확인할 수 있습니다.

> ⚠️ **트러블슈팅 — Langfuse OTLP 트레이싱 실패:**
>
> `Failed to export span batch` 또는 `Internal Server Error` 에러가 발생하면
> Langfuse의 S3(MinIO) credentials가 설정되지 않은 것일 수 있습니다.
>
> ```bash
> # Langfuse web pod에서 S3 secret key 확인
> kubectl exec $(kubectl get po -n observability -l app=web \
>   -o jsonpath='{.items[0].metadata.name}') \
>   -n observability -- env | grep S3.*SECRET
> ```
>
> `SECRET_ACCESS_KEY`가 비어있으면 `manifests/langfuse-values.yaml`에
> S3 auth 설정을 추가하고 Helm upgrade를 실행하세요:
> ```yaml
> s3:
>   auth:
>     rootUser: minio
>     rootPassword: <MinIO root-password>
> ```
> ```bash
> helm upgrade langfuse langfuse/langfuse -n observability -f manifests/langfuse-values.yaml
> kubectl rollout restart deployment langfuse-web langfuse-worker -n observability
> ```

> ⚠️ **참고 — 로컬 데모의 제한사항:**
>
> 로컬 데모(`demo.py`)는 모든 LLM 호출을 vLLM(qwen3-8b)으로 직접 보냅니다.
> Bifrost 멀티모델 라우팅(vLLM → Bedrock → OpenAI)은 K8s 클러스터 내에서
> `app/` 코드가 동작할 때 활성화됩니다. 로컬 데모에서는 쿼리 분류와 모델 선택은
> 수행하지만, 실제 모델 전환은 일어나지 않습니다.

---

## 전체 상태 검증

모든 컴포넌트가 정상 동작하는지 확인합니다:

```bash
echo "=== GPU NodePool ==="
kubectl get nodepool

echo "=== GPU Nodes ==="
kubectl get nodeclaim

echo "=== AI Inference (Bifrost + vLLM) ==="
kubectl get po -n ai-inference

echo "=== Observability (Langfuse) ==="
kubectl get po -n observability

echo "=== PVC Status ==="
kubectl get pvc -n observability
```

### vLLM 추론 테스트

```bash
# vLLM 서비스 포트포워딩
kubectl port-forward svc/vllm 8000:8000 -n ai-inference &

# 추론 요청
curl http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "qwen3-8b",
    "messages": [{"role": "user", "content": "Hello, how are you?"}],
    "max_tokens": 100
  }'
```

### Bifrost 게이트웨이 테스트

```bash
# Bifrost 서비스 포트포워딩
kubectl port-forward svc/bifrost 8080:8080 -n ai-inference &

# Bifrost를 통한 추론 요청 (provider/model 형식)
curl -s http://localhost:8080/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer test-1234" \
  -d '{
    "model": "self-hosted-vllm/qwen3-8b",
    "messages": [{"role": "user", "content": "Hello"}],
    "max_tokens": 30
  }'
```

실제 테스트 결과:

```json
{
  "id": "chatcmpl-...",
  "object": "chat.completion",
  "model": "qwen3-8b",
  "choices": [{"message": {"role": "assistant", "content": "Hello! ..."}}],
  "provider": "self-hosted-vllm"
}
```

> Bifrost가 `self-hosted-vllm` provider를 통해 vLLM으로 정상 라우팅됩니다. 응답 지연 시간은 약 900ms입니다.

---

## GPU 노드 비용 관리

테스트가 끝나면 vLLM을 스케일 다운하여 GPU 노드 비용을 절약할 수 있습니다.
Karpenter의 `consolidateAfter: 30s` 설정에 의해 GPU 워크로드가 없으면 노드가 자동으로 정리됩니다.

### GPU 노드 내리기

```bash
# vLLM 스케일 다운 → 30초 후 GPU 노드 자동 정리
kubectl scale deployment vllm -n ai-inference --replicas=0

# GPU 노드 정리 확인
kubectl get nodeclaim
kubectl get nodes -l node-type=gpu-inference
```

> NodeClaim이 사라지고 `node-type=gpu-inference` 노드가 없으면 GPU 비용이 발생하지 않습니다.
> Bifrost, Langfuse 등 나머지 컴포넌트는 ARM64(Graviton) 노드에서 계속 동작합니다.

### GPU 노드 다시 올리기

```bash
kubectl scale deployment vllm -n ai-inference --replicas=1
```

Karpenter가 g5 Spot 노드를 자동 프로비저닝하고, 모델 다운로드까지 3~5분 소요됩니다.

> ⚠️ **Bifrost Bedrock 재등록 필요:**
> GPU 노드를 내렸다 올리는 것과 별개로, Bifrost pod가 재시작된 경우
> config_store(emptyDir)가 초기화되므로 Bedrock provider를 재등록해야 합니다:
> ```bash
> python3 register_bedrock.py
> ```

---

## 리소스 정리

```bash
# 데모 앱 삭제
kubectl delete -f manifests/demo-app-deployment.yaml

# Langfuse 삭제
helm uninstall langfuse -n observability
kubectl delete pvc --all -n observability

# vLLM 삭제
kubectl delete -f manifests/vllm-deployment.yaml

# Bifrost 삭제
helm uninstall bifrost -n ai-inference

# GPU NodePool 삭제
kubectl delete -f manifests/gpu-nodepool.yaml

# StorageClass 삭제
kubectl delete -f manifests/ebs-storageclass.yaml

# EKS 클러스터 삭제
eksctl delete cluster --name $CLUSTER_NAME --region ap-northeast-2
```

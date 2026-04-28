# Self-Managed Agentic AI Platform on Amazon EKS

EKS Auto Mode 기반의 자체 관리형 Agentic AI 플랫폼입니다. Bifrost AI Gateway로 멀티모델 라우팅을, Langfuse로 LLM 트레이싱을 구현합니다.

## 아키텍처

```
[사용자] → [Demo App (FastAPI + LangGraph)]
                    ↓
            [Bifrost AI Gateway]
              ↙            ↘
    [vLLM (Qwen3-8B)]   [Amazon Bedrock (Claude)]
                    ↓
            [Langfuse (트레이싱)]
```

| 레이어 | 구성 요소 | 역할 |
|--------|-----------|------|
| 인프라 | EKS Auto Mode + Karpenter | GPU 노드 자동 프로비저닝 (Spot g5) |
| 게이트웨이 | Bifrost v1.4.14 | 멀티모델 라우팅 (`provider/model` 형식) |
| 추론 | vLLM v0.17.1 | Qwen3-8B 자체 호스팅 |
| 관측성 | Langfuse v3 (SDK v4) | LLM 트레이싱 + 비용 추적 (자체 호스팅) |
| 앱 | LangGraph + FastAPI | 멀티 에이전트 워크플로우 |

## 멀티모델 라우팅

쿼리 복잡도에 따라 자동으로 모델을 선택합니다:

| 문의 유형 | 모델 | Provider | 비용 |
|-----------|------|----------|------|
| simple (FAQ) | `self-hosted-vllm/qwen3-8b` | vLLM | $0 (GPU 인프라만) |
| complex (기술) | `bedrock/global.anthropic.claude-haiku-4-5-20251001-v1:0` | Bedrock | API 과금 |

ConfigMap의 모델 이름만 변경하면 앱 코드 수정 없이 라우팅을 전환할 수 있습니다.

## 프로젝트 구조

```
app/                              # 데모 애플리케이션
├── Dockerfile
├── main.py                       # FastAPI 엔트리포인트
├── config.py                     # Bifrost/Langfuse 설정
├── state.py                      # LangGraph 상태 정의
├── tracing.py                    # Langfuse v4 트레이싱
├── workflow.py                   # LangGraph 워크플로우
└── agents/
    ├── orchestrator.py           # 쿼리 분류 에이전트
    ├── rag_agent.py              # RAG 에이전트
    ├── document_agent.py         # 문서 분석 에이전트
    └── evaluation_agent.py       # 응답 평가 에이전트
manifests/                        # Kubernetes 매니페스트
├── ebs-storageclass.yaml         # EBS StorageClass (EKS Auto Mode)
├── gpu-nodepool.yaml             # Karpenter GPU NodePool
├── bifrost-values.yaml           # Bifrost Helm values
├── bifrost-config-patch.yaml     # Bifrost ConfigMap (vLLM + Bedrock)
├── vllm-deployment.yaml          # vLLM Deployment + Service
├── langfuse-values.yaml          # Langfuse Helm values
└── demo-app-deployment.yaml      # 데모 앱 Deployment + ConfigMap
demo.py                           # 로컬 데모 스크립트
register_bedrock.py               # Bifrost Bedrock 등록 스크립트
```

## 사전 준비

- AWS CLI v2 + `kubectl` + `eksctl` + Helm 3.x
- HuggingFace 토큰 ([Qwen/Qwen3-8B](https://huggingface.co/Qwen/Qwen3-8B))
- GPU 인스턴스(g5) 서비스 할당량

## 빠른 시작

자세한 설치 과정은 [INSTALL.md](INSTALL.md)를 참고하세요.

```bash
# 1. 클러스터 생성
eksctl create cluster --name $CLUSTER_NAME --region ap-northeast-2 --enable-auto-mode

# 2. 기본 인프라
kubectl apply -f manifests/ebs-storageclass.yaml
kubectl apply -f manifests/gpu-nodepool.yaml

# 3. Bifrost + vLLM
kubectl create namespace ai-inference
helm install bifrost bifrost/bifrost -n ai-inference -f manifests/bifrost-values.yaml
kubectl apply -f manifests/bifrost-config-patch.yaml
kubectl apply -f manifests/vllm-deployment.yaml

# 4. Langfuse
helm install langfuse langfuse/langfuse -n observability --create-namespace -f manifests/langfuse-values.yaml

# 5. 데모 앱
kubectl apply -f manifests/demo-app-deployment.yaml
```

## 설정값 커스터마이징

플레이스홀더(`<...>`)가 포함된 파일들을 실제 값으로 교체해야 합니다:

| 플레이스홀더 | 파일 | 설명 |
|-------------|------|------|
| `<AWS_ACCOUNT_ID>` | `buildspec.yml`, `codebuild-policy.json`, `demo-app-deployment.yaml` | AWS 계정 ID |
| `<BIFROST_ENCRYPTION_KEY>` | `bifrost-values.yaml`, `bifrost-config-patch.yaml` | Bifrost 암호화 키 |
| `<POSTGRES_PASSWORD>` | `langfuse-values.yaml` | PostgreSQL 비밀번호 |
| `<CLICKHOUSE_PASSWORD>` | `langfuse-values.yaml` | ClickHouse 비밀번호 |
| `<REDIS_PASSWORD>` | `langfuse-values.yaml` | Redis 비밀번호 |
| `<MINIO_ROOT_PASSWORD>` | `langfuse-values.yaml` | MinIO root 비밀번호 |
| `<NEXTAUTH_SECRET>` | `langfuse-values.yaml` | NextAuth 시크릿 |
| `<LANGFUSE_SALT>` | `langfuse-values.yaml` | Langfuse salt |
| `<LANGFUSE_ENCRYPTION_KEY>` | `langfuse-values.yaml` | Langfuse 암호화 키 |

## 로컬 데모

vLLM + Langfuse를 port-forward하여 로컬에서 멀티 에이전트 워크플로우를 테스트할 수 있습니다:

```bash
# port-forward
kubectl port-forward svc/vllm 8000:8000 -n ai-inference &
kubectl port-forward svc/langfuse-web 3000:3000 -n observability &

# 환경 설정
python3 -m venv .venv && source .venv/bin/activate
.venv/bin/pip install langchain_openai langgraph langfuse python-dotenv

# .env 파일 생성 (.env.example을 복사하여 실제 값으로 수정)
cp .env.example .env
# .env 파일을 열어 Langfuse API 키 등 실제 값으로 수정
# vi .env

# 실행
.venv/bin/python demo.py
```



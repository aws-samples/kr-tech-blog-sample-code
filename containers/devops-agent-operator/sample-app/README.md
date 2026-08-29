# Sample App — CodeBuild 기반 데모

DevOps Agent Operator의 장애 감지 → 자동 트러블슈팅 데모를 위한 샘플 애플리케이션입니다.

CodeBuild로 이미지를 빌드하고 EKS에 배포하여, 버그 버전 배포 시 Operator가 자동으로 장애를 감지하고 데이터를 수집하는 전체 흐름을 시연합니다.

## 구조

```
sample-app/
├── app.py                    # 애플리케이션 코드 (데모 시 stable/buggy로 교체)
├── versions/
│   ├── stable.py             # 정상 버전 (기본 config 사용)
│   └── buggy.py              # 버그 버전 (APP_CONFIG 필수, 미설정 시 crash)
├── Dockerfile                # 컨테이너 이미지 빌드
├── buildspec.yml             # CodeBuild 빌드 스펙
├── demo-run.sh               # 데모 실행 스크립트 (stable/buggy/status/cleanup)
├── deploy.sh                 # 로컬 Docker 빌드 & 배포
├── deploy-app.sh             # ConfigMap 기반 배포 (이미지 빌드 없이)
├── build-in-cluster.sh       # Kaniko 기반 클러스터 내 빌드
└── k8s-deployment.yaml.tpl   # Kubernetes Deployment 템플릿
```

## 사전 요구사항

- EKS 클러스터 (Operator가 배포된 상태)
- AWS CLI 설정 완료
- CodeBuild 프로젝트 생성 (아래 설정 참조)
- ECR 리포지토리 생성
- AWS DevOps Agent에서 GitHub repository 연동 완료
  - Agent가 장애 발생 시 관련 commit diff를 자동으로 추적하려면 소스 repository 연결이 필요합니다
  - 설정 방법: [Connecting to GitHub](https://docs.aws.amazon.com/devopsagent/latest/userguide/connecting-to-cicd-pipelines-connecting-github.html)

## 환경 설정

`demo-run.sh` 상단의 변수를 자신의 환경에 맞게 수정합니다:

```bash
AWS_ACCOUNT_ID="<YOUR_AWS_ACCOUNT_ID>"      # 예: 123456789012
AWS_REGION="<YOUR_AWS_REGION>"              # 예: ap-northeast-2
ECR_REPO="sample-app"                       # ECR 리포지토리 이름
S3_BUCKET="<YOUR_CODEBUILD_SOURCE_BUCKET>"  # CodeBuild 소스용 S3 버킷
CODEBUILD_PROJECT="<YOUR_CODEBUILD_PROJECT>" # CodeBuild 프로젝트 이름
```

## CodeBuild 프로젝트 설정

### 1. S3 소스 버킷 생성

```bash
aws s3 mb s3://<YOUR_CODEBUILD_SOURCE_BUCKET> --region <YOUR_AWS_REGION>
```

### 2. ECR 리포지토리 생성

```bash
aws ecr create-repository --repository-name sample-app --region <YOUR_AWS_REGION>
```

### 3. CodeBuild 프로젝트 생성

콘솔 또는 CLI로 다음 설정의 CodeBuild 프로젝트를 생성합니다:

| 항목 | 값 |
|------|-----|
| 소스 | S3 (`s3://<YOUR_CODEBUILD_SOURCE_BUCKET>/source.zip`) |
| 환경 이미지 | `aws/codebuild/amazonlinux2-x86_64-standard:5.0` |
| 권한 모드 | Privileged (Docker 빌드용) |
| 빌드 스펙 | `sample-app/buildspec.yml` |
| 환경 변수 | `AWS_DEFAULT_REGION` = `<YOUR_AWS_REGION>` |

CodeBuild IAM Role에 ECR push 권한과 S3 read 권한이 필요합니다.

## 사용 방법

### 데모 스크립트 (CodeBuild 사용)

```bash
cd sample-app/

# 정상 버전 빌드 & 배포
./demo-run.sh stable

# 버그 버전 배포 → CrashLoopBackOff 발생 → Operator 감지
./demo-run.sh buggy

# 상태 확인
./demo-run.sh status

# 정리
./demo-run.sh cleanup
```

### 로컬 Docker 빌드 (CodeBuild 없이)

```bash
# 환경 변수 설정
export AWS_ACCOUNT_ID="<YOUR_AWS_ACCOUNT_ID>"
export AWS_REGION="<YOUR_AWS_REGION>"

./deploy.sh
```

### ConfigMap 기반 배포 (이미지 빌드 없이)

```bash
./deploy-app.sh
```

## 데모 시나리오

### 정상 → 장애 발생 흐름

1. **stable 배포**: `app.py`는 기본 config(`{"app_name": "sample-app", "port": 8080}`)를 사용하므로 정상 동작
2. **buggy 배포**: `app.py`가 `APP_CONFIG` 환경변수를 필수로 요구하도록 변경. Deployment에 해당 환경변수가 없으므로 즉시 crash
3. **Operator 감지**: CrashLoopBackOff 상태를 감지하고, pod manifest/logs/events/node logs를 수집
4. **결과 확인**: S3에 인시던트 데이터가 저장되고, Webhook을 통해 DevOps Agent에 알림 전달

### 버그의 핵심

```python
# stable: 기본값 사용
config_str = os.environ.get("APP_CONFIG", '{"app_name": "sample-app", "port": 8080}')

# buggy: 환경변수 필수 → Deployment에 미설정 → crash
config_str = os.environ.get("APP_CONFIG")
if config_str is None:
    sys.exit(1)  # FATAL
```

실제 운영에서 발생할 수 있는 "리팩토링 시 기본값 제거" 패턴을 재현합니다.


## 트러블슈팅

| 증상 | 대응 |
|------|------|
| 빌드 실패 | `aws codebuild batch-get-builds --ids <BUILD_ID>` 로 에러 확인 |
| Pod가 계속 Running | stable 버전 배포됨. `./demo-run.sh buggy` 재실행 |
| Operator가 감지 안 함 | `kubectl rollout restart deploy/devops-agent-operator -n devops-agent-operator-system` |
| S3에 인시던트 없음 | Operator 환경변수에 `S3_BUCKET` 설정 확인 |

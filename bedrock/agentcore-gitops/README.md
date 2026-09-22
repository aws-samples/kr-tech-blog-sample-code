# AgentCore GitOps

Amazon EKS의 Argo CD와 ACK를 사용해 Amazon Bedrock AgentCore Runtime과 Gateway를 관리하는 AWS Tech Blog 한국어 예제입니다. 에이전트는 EKS Pod가 아닌 AgentCore Runtime에서 실행합니다. Strands Agents SDK와 `global.anthropic.claude-sonnet-5`를 사용합니다.

이 샘플은 비운영 전용 계정을 대상으로 합니다. 공식 ACK 1.15.1은 Runtime을 지원하지만 Gateway HTTP Runtime target에는 포함된 확장 패치가 필요합니다. Argo Rollouts는 PostSync AnalysisRun에 사용하며 blue/green, canary 또는 자동 rollback은 구현하지 않습니다.

## 저장소 위치와 준비

이 디렉터리는 `kr-tech-blog-sample-code/bedrock/agentcore-gitops`에 배치합니다. 원본 저장소를 자신의 GitHub 계정으로 포크하거나 같은 디렉터리 구조로 복사합니다. GitOps의 쓰기 대상은 자신이 관리하는 저장소입니다. 아래 명령은 모두 `bedrock/agentcore-gitops`에서 실행합니다.

- Node.js 24 이상, npm, AWS CLI v2, Docker Buildx, Helm, kubectl, uv, jq, GitHub CLI를 준비합니다.
- Python 실행 버전과 라이브러리는 `agent/pyproject.toml` 및 lockfile을 따릅니다. Go 빌드는 컨테이너 안에서 실행합니다.
- AWS 프로파일 기본값은 `default`, 리전 기본값은 `us-east-1`입니다. 모델의 사용 권한과 Global inference profile의 데이터 처리 정책을 확인합니다.
- EKS 노드, NAT Gateway, ALB, ECR, 로그와 모델 호출에는 비용이 발생합니다.
- `eks-ack-agentcore`라는 클러스터 및 ECR 이름을 사용하므로 기존 다른 프로젝트와 이름이 충돌하는 환경에는 실행하지 않습니다.

## 1. 인프라와 플랫폼 설치

```bash
export AWS_PROFILE=default
export AWS_REGION=us-east-1
export ADMIN_CIDR=YOUR_PUBLIC_IPV4/32
export ADMIN_PRINCIPAL_ARN=YOUR_IAM_USER_OR_ROLE_ARN
npm ci
source scripts/environment.sh
npx cdk bootstrap "aws://$CDK_DEFAULT_ACCOUNT/$AWS_REGION"
bash scripts/deploy-foundation.sh
bash scripts/build-ack-controller.sh
bash scripts/install-platform.sh
```

placeholder는 실제 값으로 교체합니다. STS session ARN은 EKS Access Entry의 IAM role ARN 대신 사용할 수 없습니다. `ADMIN_PRINCIPAL_ARN`을 명시하지 않으면 현재 AWS identity를 사용하며, assumed-role 세션이면 IAM role ARN을 요청하고 중단합니다.

CDK 스크립트는 테스트, synth와 diff 후 승인 프롬프트 없이 리소스를 생성합니다. 실행 전에 diff와 소스를 검토하세요. ECR은 삭제 시 보존하고 재설치 시 import합니다. 태그 없는 이미지만 수명주기 정리 대상으로 하므로 릴리스 이미지는 수동으로 관리해야 합니다.

ACK 이미지는 자신의 ECR에서 빌드합니다. 생성되는 `.state/ack-image-values.json`과 CRD 일곱 개의 빌드 정보를 설치 전에 검사합니다. 확장 CRD를 선적용한 후 Helm에는 `--skip-crds`를 전달합니다. 사내 프록시가 필요한 경우 승인된 `GOPROXY`를 설정하되 checksum 검증은 끄지 마세요.

## 2. GitOps 저장소 설정

`gitops/application.yaml`과 `gitops/project.yaml`의 `YOUR_GITHUB_ORG/YOUR_REPOSITORY`를 자신의 저장소로 교체합니다. Application 경로는 다음과 같아야 합니다.

```yaml
source:
  repoURL: ssh://git@github.com/YOUR_GITHUB_ORG/YOUR_REPOSITORY.git
  targetRevision: main
  path: bedrock/agentcore-gitops/charts/agentcore-agent
  helm:
    releaseName: devops-agent
    valueFiles:
      - ../../gitops/environments/dev.yaml
```

환경별 `dev.yaml`은 chart 기준 상대 경로입니다. 설치 스크립트는 Git 루트에서 실제 chart까지의 경로, 두 manifest의 저장소 주소와 `GITHUB_REPOSITORY`가 일치하는지 검증합니다. 읽기 전용 deploy key는 지정한 저장소에만 등록합니다. 이전 저장소의 key를 다른 저장소에 재사용하지 않습니다.

```bash
export GITHUB_REPOSITORY=YOUR_GITHUB_ORG/YOUR_REPOSITORY
bash scripts/build-agent.sh "blog-v1-$(date -u +%Y%m%dT%H%M%SZ)" blog-v1
cat .state/image-uri
```

`gitops/environments/dev.yaml`에 다음 값을 설정합니다.

| 값 | 입력 |
|---|---|
| `runtime.imageUri` | `.state/image-uri`의 ECR digest |
| `runtime.roleArn` | `.state/outputs.json`의 `ExecutionRoleArn` |
| `runtime.release` | `v1` |
| `runtime.buildRevision` | 위 빌드 명령의 `blog-v1` |
| `gateway.enabled`, `analysis.enabled`, `endpoint.enabled` | 첫 배포에서는 모두 `false` |

두 manifest와 환경 values를 검토해 자신의 저장소에 커밋하고 푸시합니다. 계정 ID와 ARN은 비밀키는 아니지만 공개할 운영 식별자가 아닐 수 있으므로 비공개 배포 저장소 또는 비운영 계정 사용을 검토하세요. `.state/`는 절대 커밋하지 않습니다.

```bash
bash scripts/configure-gitops.sh
bash scripts/wait-gitops.sh
kubectl --context eks-ack-agentcore -n agentcore get agentruntimes -o yaml
```

## 3. Gateway와 실제 호출 검증

Runtime이 `READY`가 되면 상태의 Runtime ARN과 ID를 읽어 같은 `dev.yaml`에 입력합니다.

| 값 | 입력 |
|---|---|
| `gateway.runtimeArn` | `status.ackResourceMetadata.arn` |
| `gateway.roleArn` | CDK 출력의 `GatewayExecutionRoleArn` |
| `gateway.enabled`, `analysis.enabled` | `true` |
| `analysis.imageUri` | `gateway_probe.py`를 포함한 `.state/image-uri` |
| `endpoint.runtimeId` | `status.agentRuntimeID` |
| `endpoint.enabled` | `false` 유지. Gateway는 `DEFAULT` 사용 |

변경을 커밋하고 푸시한 뒤 다음을 실행합니다.

```bash
bash scripts/wait-gitops.sh
bash scripts/invoke-gateway.sh
kubectl --context eks-ack-agentcore -n agentcore get analysisruns,jobs,pods
```

`runtime.imageUri`는 배포할 에이전트 이미지이고 `analysis.imageUri`는 검증 Job 이미지입니다. ECR push만으로 배포되지 않습니다. Git values의 이미지 digest를 변경해야 ACK가 새 Runtime 버전을 만듭니다. `DEFAULT` 전환은 PostSync보다 먼저 발생합니다.

## 4. 다음 릴리스와 연속 요청 시험

```bash
bash scripts/build-agent.sh "blog-v2-$(date -u +%Y%m%dT%H%M%SZ)" blog-v2
```

새 digest, `runtime.release: v2`, `runtime.buildRevision: blog-v2`를 Git에 반영합니다. 배포 전후의 단발 호출뿐 아니라 `agent/rollout_probe.py run --help`로 지속 트래픽 도구를 확인할 수 있습니다. 최대 부하, timeout과 요청 상한을 정한 비운영 시험에만 사용하세요. 오류 없는 짧은 표본을 모든 부하의 무중단 보장으로 해석하지 않습니다.

로컬 코드 검증을 위해 `GITOPS_VALUES_FILE`을 지정할 수도 있지만 이는 Application의 values override이며 새 Git 커밋의 Pull 검증이 아닙니다. 승인된 values가 Git에 반영되기 전에 override를 제거하지 마세요.

## 점검과 정리

```bash
npm run check
npm test
uv run --directory agent pytest
helm lint charts/agentcore-agent -f docs/aws-tech-blog/snippets/dev-values.example.yaml
bash scripts/argo-admin.sh
```

관리 ALB는 허용한 IPv4 /32만 접근할 수 있으며 데모 자체 서명 인증서를 사용합니다. 비밀번호는 마지막 명령으로 로컬 터미널에서만 확인합니다. 운영에는 SSO, 정식 인증서, HA와 관측 설정이 필요합니다.

공개용 폴더의 단위 테스트, CDK 합성, Helm 렌더링과 기존 AWS Runtime 호출을 확인했습니다. 이 monorepo 커밋으로 새 Git-only 환경을 처음부터 배포한 검증은 별도입니다. 배포 전 이미지 취약점을 다시 스캔하고 public EKS endpoint, managed IAM policy 및 wildcard 권한의 적합성을 검토하세요. 문서에 기록된 실험 결과는 운영 준비 완료나 보안 승인을 의미하지 않습니다.

```bash
CONFIRM_DESTROY=eks-ack-agentcore bash scripts/destroy.sh
```

삭제는 프로젝트 전용 클러스터에서만 수행합니다. ACK 리소스와 ALB를 먼저 지우고 컨트롤러, CDK 스택 순서로 정리합니다. 조직 GuardDuty가 생성한 VPC endpoint는 별도 소유권 검토가 필요할 수 있습니다. ECR 이미지, 과거 로그와 Git deploy key는 보존하므로 잔여 비용과 접근 권한도 정리하세요. CDKToolkit과 다른 프로젝트 리소스는 삭제하지 않습니다.

## 문서

- [AWS Tech Blog 원고](docs/aws-tech-blog/article.md)
- [Helm chart 코드 해설](docs/aws-tech-blog/helm-highlights.md)
- [ACK 확장 범위와 출처](patches/ack-controller/README.md)

이 샘플의 제출은 상위 저장소의 `CONTRIBUTING.md`와 라이선스 검토 절차를 따릅니다. 이 문서는 AWS 보안 승인 또는 프로덕션 사용 적합성 보증이 아닙니다.

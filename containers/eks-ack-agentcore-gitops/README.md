# EKS ACK AgentCore GitOps

Amazon EKS의 Argo CD와 ACK를 사용해 Amazon Bedrock AgentCore Runtime과 Gateway를 관리하는 실습 코드입니다. 에이전트는 EKS Pod가 아닌 AgentCore Runtime에서 실행합니다. Strands Agents SDK와 `global.anthropic.claude-sonnet-5`를 사용합니다.

이 샘플은 비운영 전용 계정을 대상으로 합니다. 공식 ACK 1.15.1은 Runtime을 지원하지만 Gateway HTTP Runtime target에는 포함된 확장 패치가 필요합니다. Argo Rollouts는 PostSync AnalysisRun에 사용하고 있으며 ArgoRollout의 B/G나 Canary 배포를 지원하지는 않습니다.


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
  path: containers/eks-ack-agentcore-gitops/charts/agentcore-agent
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

### curl로 릴리스 전환 관찰

새 버전 배포 전에 아래 명령을 시작합니다. 기존 session ID 요청과 매번 새 session ID를 만드는 요청을 교대로 보내며, 응답의 `release`와 `build_revision`이 바뀌는지 기록합니다.

```bash
bash scripts/watch-gateway-curl.sh --session-mode both --count 60 --interval 3
```

AWS CLI의 `default` 프로파일로 Gateway 주소와 서명용 자격 증명을 가져오고 실제 curl로 호출합니다. 키와 토큰은 curl 표준입력으로 전달하며, 요청 결과에 포함하지 않습니다. 서명용 자격 증명은 요청마다 다시 조회합니다. HTTP 오류와 연결 실패도 기록하면서 관찰을 계속하고 실패가 있으면 마지막 종료 코드는 1입니다.

기본 상한은 요청 60건 또는 300초입니다. `--session-mode new`는 신규 세션만, `existing`은 같은 세션만 호출합니다. `both`는 두 종류를 교대로 호출하고 `--count`는 총 요청 수입니다. 기존 세션의 이전 버전 유지를 보려면 새 버전 배포 전에 첫 요청을 보내야 합니다. 이 도구는 순차 관찰용이며 동시 트래픽 시험이나 무중단 보장 도구가 아닙니다. 각 요청에는 모델 사용 비용이 발생합니다.

| 출력 필드 | 의미 |
|---|---|
| `lane` | 신규 세션 `new` 또는 기존 세션 `existing` |
| `release`, `build_revision` | 응답한 앱의 릴리스와 빌드 식별자 |
| `changed` | 같은 lane의 직전 성공 응답과 릴리스 또는 빌드가 달라졌는지 여부 |
| `ok`, `http_status`, `error` | 성공 여부, HTTP 상태와 실패 종류 |
| `latency_seconds` | curl 실행부터 종료까지 걸린 시간 |

결과는 표준출력에 JSONL로, 마지막 요청 및 실패 수는 표준오류에 출력됩니다. AWS 인증 조회가 실패하면 요청을 시작하지 않고 중단합니다. Gateway 주소를 직접 지정하려면 `--gateway-url`에 선택한 리전의 AgentCore Gateway HTTPS 기본 주소를 전달합니다. 타깃 경로는 자동으로 붙습니다. 전체 옵션은 `bash scripts/watch-gateway-curl.sh --help`로 확인합니다.

## 점검과 정리

```bash
npm run check
npm test
uv run --directory agent pytest
helm lint charts/agentcore-agent -f gitops/environments/dev.yaml
bash scripts/argo-admin.sh
```

관리 ALB는 허용한 IPv4 /32만 접근할 수 있으며 데모 자체 서명 인증서를 사용합니다. 비밀번호는 마지막 명령으로 로컬 터미널에서만 확인합니다. 운영에는 SSO, 정식 인증서, HA와 관측 설정이 필요합니다.

검사 명령은 위 단계에서 환경 값을 채운 뒤 실행합니다. 기본 values의 빈 이미지 URI와 역할 ARN은 실제 값으로 바꿔야 합니다. curl 테스트는 가짜 자격 증명과 로컬 HTTPS 서버를 사용하며 AWS 모델을 호출하지 않습니다. 이 경로의 아티팩트로 새 Git-only 환경을 처음부터 배포하는 검증은 별도입니다. 운영 적용 전 이미지 취약점, public EKS endpoint, IAM 권한을 검토하세요.

```bash
CONFIRM_DESTROY=eks-ack-agentcore bash scripts/destroy.sh
```

삭제는 프로젝트 전용 클러스터에서만 수행합니다. ACK 리소스와 ALB를 먼저 지우고 컨트롤러, CDK 스택 순서로 정리합니다. 조직 GuardDuty가 생성한 VPC endpoint는 별도 소유권 검토가 필요할 수 있습니다. ECR 이미지, 과거 로그와 Git deploy key는 보존하므로 잔여 비용과 접근 권한도 정리하세요. CDKToolkit과 다른 프로젝트 리소스는 삭제하지 않습니다.

# 기존 Amazon EKS와 GitOps 환경에서 ACK로 Amazon Bedrock AgentCore 관리하기

AI 에이전트를 업무와 서비스에 적용하려는 기업이 늘면서, 에이전트를 개발하는 일과 함께 이를 배포하고 운영하는 방법도 중요해지고 있습니다. 이미 Amazon Elastic Kubernetes Service(Amazon EKS)를 공통 플랫폼으로 도입하고 GitOps를 배포 표준으로 사용하는 기업이라면, 에이전트도 기존의 코드 리뷰와 배포 승인, 변경 이력 관리 절차 안에서 운영하고자 합니다.

새로운 실행 환경을 도입할 때마다 관리 도구와 배포 절차를 따로 마련하면 플랫폼 팀이 관리해야 할 대상이 늘어납니다. 에이전트 실행에 Amazon Bedrock AgentCore를 사용하면서도 Git에서 변경을 검토하고 Argo CD에서 배포 결과를 확인할 수 있다면, 이미 구축한 EKS와 GitOps 운영 체계를 활용할 수 있습니다.

이 글에서는 AWS Controllers for Kubernetes(ACK)를 사용해 AgentCore를 기존 EKS 플랫폼에서 관리하고 GitOps 방식으로 배포하는 방법을 소개합니다. ACK는 Kubernetes에 선언한 AWS 리소스의 구성을 AWS API에 반영합니다. 개발자는 Helm chart와 환경별 values로 에이전트의 원하는 상태를 정의하고, Argo CD는 Git 변경을 가져와 적용합니다. EKS에서는 배포 컨트롤러가 동작하며, 에이전트 코드는 AgentCore Runtime에서 실행됩니다.

예제에서는 AWS Cloud Development Kit(AWS CDK)로 기반 인프라를 구성하고 Helm으로 필요한 컨트롤러를 설치합니다. 이어서 Strands Agents SDK로 작성한 에이전트를 배포하고 AgentCore Gateway를 통해 호출합니다. 마지막으로 이미지 변경에 따른 Runtime 재배포와 Argo Rollouts의 배포 후 분석을 확인합니다. 예제 모델은 Amazon Bedrock의 Claude Sonnet 5 Global inference profile입니다.

## 기존 플랫폼에 AgentCore 연결하기

이 구성은 EKS와 Argo CD를 운영하는 플랫폼 팀이 에이전트의 배포 경로도 함께 관리하려는 경우를 대상으로 합니다. Git에는 어떤 이미지를 배포할지 기록하고, Argo CD에서는 해당 선언이 반영됐는지 확인합니다. ACK가 AWS API 호출과 상태 동기화를 맡으므로 에이전트마다 별도의 AWS 배포 스크립트를 작성할 필요를 줄일 수 있습니다.

배포할 에이전트의 이미지 digest를 Git에서 바꾸면 ACK가 Runtime을 업데이트합니다. 배포 후 검증 Job은 Gateway에 실제 요청을 보내 예상한 릴리스가 응답하는지 확인합니다. 플랫폼 팀은 Kubernetes에 익숙한 도구로 배포 상태를 살펴보고, AgentCore Runtime에 에이전트 실행을 맡깁니다.

## 아키텍처와 리소스 소유권

![Git의 Helm 선언을 EKS의 Argo CD와 ACK가 AgentCore에 반영하고, 애플리케이션은 Gateway를 거쳐 Runtime과 Bedrock을 호출하는 아키텍처](figures/architecture.png)

*그림 1. 배포 컨트롤러는 EKS에, 에이전트 실행 환경은 AgentCore에 둡니다. 관리용 ALB는 Argo CD 접속에만 사용합니다. NAT, VPC endpoint, 관리자에서 EKS API로 가는 경로는 생략했습니다. Global 모델 처리는 검증 리전 밖으로 라우팅될 수 있습니다.*

관리 경로는 `Git → Argo CD → Kubernetes custom resource → ACK → AWS API`입니다. 실제 요청은 `애플리케이션 → AgentCore Gateway → AgentCore Runtime → Amazon Bedrock`을 통과합니다. EKS에 에이전트 애플리케이션 Pod를 배포하지 않으므로, 릴리스마다 Deployment나 ReplicaSet이 만들어지는 구성은 아닙니다.

같은 리소스를 서로 다른 도구가 수정하지 않도록 소유권을 나눕니다.

| 담당 도구 | 관리 대상 |
|---|---|
| AWS CDK | VPC, EKS, ECR, IAM 역할, EKS add-on과 Pod Identity association |
| 플랫폼 Helm 설치 | AWS Load Balancer Controller, Argo CD, ACK, Argo Rollouts |
| Argo CD | 에이전트 chart의 Runtime, Gateway, GatewayTarget, 검증 리소스 |
| ACK | Kubernetes 선언에 대응하는 AWS AgentCore 리소스 |
| Argo Rollouts | AnalysisRun과 실제 호출을 수행하는 검증 Job |
| 플랫폼 설치 스크립트 | 관리용 Argo CD Ingress와 데모 인증서 |

기반 인프라는 두 가용 영역의 프라이빗 서브넷에 ARM64 `m7g.large` 노드 두 대를 배치합니다. 재현 편의를 위해 새 EKS 클러스터를 만드는 예제입니다. 기존 클러스터에 적용할 때는 운영 중인 컨트롤러를 중복 설치하지 않고, 네임스페이스와 IAM association을 플랫폼 정책에 맞춰 통합해야 합니다.

## 사전 준비와 검증 버전

예제 저장소를 로컬에 준비하고 AWS CLI의 `default` 프로파일을 설정합니다. Node.js와 npm, Helm, kubectl, Docker Buildx, Python 실행 도구인 uv, GitHub CLI와 jq가 필요합니다. AWS CDK는 프로젝트 의존성으로 설치하며, ACK의 Go 빌드는 Docker 안에서 수행합니다. k9s는 Kubernetes 리소스를 터미널에서 확인할 때 선택적으로 사용할 수 있습니다.

검증 리전은 `us-east-1`입니다. 사용할 계정에서 AgentCore와 모델을 사용할 수 있는지 확인하고, 조직의 Service Control Policy(SCP)와 데이터 처리 정책이 Global inference profile 사용을 허용하는지 검토합니다. 관리용 EKS API와 ALB에 접속할 공인 IPv4 주소도 준비합니다.

다음은 2026년 9월 21일 재설치 검증에 사용한 주요 버전입니다. 재현성을 위해 저장소 설정과 lockfile에 고정했으며, 최신 버전 목록을 의미하지는 않습니다.

| 구성 요소 | 검증 버전 |
|---|---|
| Amazon EKS / AWS CDK 라이브러리 | Kubernetes 1.36 / 2.269.0 |
| AWS Load Balancer Controller chart | 3.5.0 |
| Argo CD chart / 애플리케이션 | 10.9.0 / v3.5.2 |
| ACK AgentCore chart / 사용자 빌드 | 1.15.1 / 1.15.1-http-runtime.1 |
| Argo Rollouts chart / 애플리케이션 | 2.43.1 / v1.10.0 |
| Strands Agents / AgentCore SDK | 1.55.1 / 1.23.0 |
| 로컬 `agentcore-agent` chart | 0.1.0 |

공식 ACK는 `AgentRuntime`을 지원합니다. 다만 검증한 ACK 1.15.1에는 Gateway의 HTTP Runtime target 스키마가 없어 이 부분에는 예제 저장소의 확장 패치를 사용합니다. 배포 방식은 Runtime 버전 업데이트와 PostSync 사후 검증입니다. 네이티브 Argo Rollouts blue/green, canary 또는 자동 rollback을 구현한 예제는 아닙니다.

## 1. AWS CDK로 기반 인프라 배포하기

CDK는 VPC, EKS와 IAM 역할을 만들고 ECR 저장소를 구성합니다. 다음은 `infra/platform-stack.ts`의 VPC 설정입니다. 두 가용 영역에 퍼블릭 서브넷과 프라이빗 서브넷을 만들며 NAT Gateway는 데모 비용을 고려해 한 대를 사용합니다.

```typescript
const vpc = new ec2.Vpc(this, 'Vpc', {
  maxAzs: 2,
  natGateways: 1,
  ipAddresses: ec2.IpAddresses.cidr('10.83.0.0/16'),
  subnetConfiguration: [
    { name: 'public', subnetType: ec2.SubnetType.PUBLIC, cidrMask: 24 },
    { name: 'private', subnetType: ec2.SubnetType.PRIVATE_WITH_EGRESS, cidrMask: 24 },
  ],
});
```

EKS 노드는 프라이빗 서브넷에 배치합니다. 에이전트 이미지가 저장될 ECR은 태그 덮어쓰기를 막고 이미지 스캔을 활성화합니다. 저장소를 `RETAIN`으로 지정했으므로 CDK 스택 삭제가 이미지 삭제로 이어지지 않습니다.

```typescript
const repository = new ecr.Repository(this, 'AgentRepository', {
  repositoryName: prefix,
  imageScanOnPush: true,
  imageTagMutability: ecr.TagMutability.IMMUTABLE,
  encryption: ecr.RepositoryEncryption.AES_256,
  lifecycleRules: [{ tagStatus: ecr.TagStatus.UNTAGGED, maxImageCount: 20 }],
  removalPolicy: RemovalPolicy.RETAIN,
});
```

저장소 루트에서 다음 순서로 실행합니다. EKS 노드, NAT, ALB와 모델 호출에는 비용이 발생합니다. 기반 배포 스크립트는 검사와 diff 후 승인 프롬프트 없이 배포하므로, 실행 전에 `infra/platform-stack.ts`와 예상 변경을 검토하세요.

```bash
export AWS_PROFILE=default
export AWS_REGION=us-east-1
aws sts get-caller-identity

npm ci
source scripts/environment.sh
npx cdk bootstrap "aws://$CDK_DEFAULT_ACCOUNT/$AWS_REGION"
bash scripts/deploy-foundation.sh

kubectl --context eks-ack-agentcore get nodes
k9s --context eks-ack-agentcore
```

`deploy-foundation.sh`는 TypeScript 검사와 테스트, strict synth, diff를 거쳐 CDK를 배포하고 kubeconfig에 `eks-ack-agentcore` context를 등록합니다. CNI 권한을 Pod Identity로 전환하는 후속 CDK 배포도 포함합니다. 출력값은 `.state/outputs.json`에 저장됩니다.

스택을 삭제한 뒤 다시 배포하는 경우에는 보존된 ECR 저장소를 `--import-existing-resources`로 새 스택에 가져옵니다. 새 EKS 생성 시에는 CNI 부트스트랩 권한을 다시 활성화합니다. 이전 환경의 `.state/cni-migrated` 파일만 보고 부트스트랩 단계를 건너뛰지 않도록 한 처리입니다.

## 2. Helm으로 플랫폼 컨트롤러 설치하기

플랫폼에는 upstream chart 네 개를 설치하고, 에이전트 리소스는 별도의 로컬 chart 하나로 관리합니다. 아래 코드는 중요한 부분만 발췌했습니다. 전체 설정과 템플릿은 [Helm 코드 해설](helm-highlights.md)에 있습니다.

```bash
bash scripts/build-ack-controller.sh
bash scripts/install-platform.sh
helm list --all-namespaces --kube-context eks-ack-agentcore
```

첫 번째 스크립트는 고정된 ACK 소스에 패치를 적용하고 테스트한 뒤 ARM64 이미지를 자신의 ECR에 올립니다. 두 번째 스크립트는 이미지와 CRD의 빌드 정보를 검사하고 컨트롤러를 설치합니다. 기본 Go 모듈 서버에 접근할 수 없는 환경에서는 조직에서 허용한 `GOPROXY`를 지정합니다. checksum 검증은 유지합니다.

설치가 끝나면 `bash scripts/argo-admin.sh`로 Argo CD URL과 초기 접속 정보를 확인합니다. 관리 ALB와 EKS API는 허용 CIDR로 접근을 제한합니다. 데모 인증서는 자체 서명이므로 브라우저 경고가 표시되며, 운영 환경에서는 정식 도메인과 인증서를 사용해야 합니다. 접속 정보나 private key를 Git 또는 블로그에 기록하지 마세요.

### AWS Load Balancer Controller: 관리용 ALB

`scripts/install-platform.sh`에서 다음 값을 Helm에 전달합니다. VPC ID는 CDK 출력으로 대체합니다.

```yaml
clusterName: eks-ack-agentcore
region: us-east-1
vpcId: vpc-0123456789abcdef0
serviceAccount:
  name: aws-load-balancer-controller
```

CDK가 이 ServiceAccount에 Pod Identity 역할을 연결합니다. Argo CD Ingress는 설치 스크립트가 별도로 생성합니다. HTTPS 443, `target-type: ip`, 허용 관리자 CIDR, HTTPS backend와 `/healthz` 검사를 지정합니다. 에이전트의 Gateway URL과 관리용 ALB URL은 용도가 다릅니다.

### Argo CD: ACK 상태를 Health에 반영

ACK 리소스의 상태를 읽는 Lua health check를 Argo CD에 추가합니다. 다음은 `config/argocd-values.yaml`의 Runtime 부분입니다.

```yaml
configs:
  cm:
    timeout.reconciliation: 30s
    timeout.reconciliation.jitter: 5s
    resource.customizations.health.bedrockagentcorecontrol.services.k8s.aws_AgentRuntime: |
      local health = {status = "Progressing", message = "Waiting for ACK reconciliation"}
      if obj.status ~= nil and obj.status.conditions ~= nil then
        for _, condition in ipairs(obj.status.conditions) do
          if condition.type == "ACK.Terminal" and condition.status == "True" then
            return {status = "Degraded", message = condition.message or "ACK terminal error"}
          end
          if condition.type == "ACK.ResourceSynced" and condition.status == "True" and obj.status.status == "READY" then
            health = {status = "Healthy", message = "AgentCore runtime READY"}
          end
        end
      end
      return health
```

Gateway와 GatewayTarget에도 같은 취지의 check를 적용합니다. AnalysisRun은 `Successful`을 `Healthy`로, `Failed`, `Error`, `Inconclusive`를 `Degraded`로 표시합니다. 이 설정은 준비 상태를 보여 줍니다. 모델 호출은 별도 검증 Job이 확인합니다.

### ACK: 감시 범위와 HTTP Runtime target 확장

```yaml
aws:
  region: us-east-1
installScope: namespace
watchNamespace: agentcore
serviceAccount:
  create: true
  name: ack-agentcore
deployment:
  nodeSelector:
    kubernetes.io/arch: arm64
reconcile:
  defaultResyncPeriod: 60
  resources:
    - AgentRuntime
    - AgentRuntimeEndpoint
    - Gateway
    - GatewayTarget
```

컨트롤러는 `agentcore` 네임스페이스를 감시하고 Pod Identity 역할로 AWS API를 호출합니다. Kubernetes Secret에 정적 AWS access key를 넣지 않습니다.

검증에 사용한 공식 ACK 1.15.1에는 Gateway HTTP Runtime target 타입이 없었습니다. 저장소의 패치는 `http.agentcoreRuntime.arn`과 `qualifier`를 타입과 CRD에 추가하고, SDK create/read/update 변환과 변경 비교까지 연결합니다. Endpoint 업데이트 관련 보정도 포함합니다. `build-ack-controller.sh`가 회귀 테스트와 ARM64 이미지 빌드를 수행하며, 설치 스크립트는 `.state/ack-image-values.json`으로 chart의 컨트롤러 이미지를 교체합니다.

Runtime, RuntimeEndpoint, Gateway, GatewayTarget CRD 네 개와 ACK 공통 CRD 세 개를 `.state/ack-crds/`에서 별도로 적용합니다. Helm에는 `--skip-crds`를 전달해 stock CRD와 확장 CRD의 소유권 충돌을 막습니다. 이 문제는 기존 클러스터 업그레이드가 아닌 새 설치에서 발견했습니다. 설치 전에 이미지와 소스 버전, CRD의 빌드 정보를 대조하므로 이전 파일을 그대로 섞어 사용할 수 없습니다. 패치 범위는 Runtime target에 한정되며 HTTP passthrough나 inference target 전체를 지원하지 않습니다.

### Argo Rollouts: 배포 후 Job 실행

Argo Rollouts chart의 추가 설정은 다음과 같습니다.

```yaml
dashboard:
  enabled: false
```

실제 검증 정의는 로컬 chart의 `AnalysisRun`에 있습니다. 여기서는 Argo Rollouts의 Job 기반 분석 기능을 사용합니다. `Rollout` 리소스나 트래픽 가중치 설정은 만들지 않습니다.

## 3. Helm chart로 Runtime과 Gateway 선언하기

### 배포 입력은 `runtime.imageUri`

이미지를 ARM64로 빌드하고 ECR에 올립니다. 태그는 매번 고유하게 지정합니다.

```bash
bash scripts/build-agent.sh "blog-v1-$(date -u +%Y%m%dT%H%M%SZ)" blog-v1
cat .state/image-uri
```

이 명령은 테스트를 실행하고 `BUILD_REVISION=blog-v1`을 이미지에 넣어 빌드한 뒤 digest를 출력합니다. 다음 values는 독자가 첫 릴리스를 준비할 때 사용할 설명용 예시입니다. 계정과 digest는 자신의 값으로 바꾸고, `roleArn`에는 `.state/outputs.json`의 `ExecutionRoleArn`을 입력합니다. 예시 릴리스 이름은 뒤의 측정 기록과 구분합니다.

```yaml
runtime:
  imageUri: "123456789012.dkr.ecr.us-east-1.amazonaws.com/eks-ack-agentcore@sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
  roleArn: "arn:aws:iam::123456789012:role/AgentCoreRuntimeExecutionRole"
  region: us-east-1
  modelId: global.anthropic.claude-sonnet-5
  release: blog-v1
  buildRevision: blog-v1
```

`release`는 앱의 환경변수로 전달하는 릴리스 이름입니다. `buildRevision`은 이미지 안의 빌드 식별자와 검증할 기대값입니다. 두 필드 모두 AWS Runtime 버전 번호를 직접 지정하지 않습니다. chart의 `appVersion`도 AWS Runtime 버전과 별개입니다.

`templates/runtime.yaml`은 이미지 값을 다음과 같이 AWS 리소스 선언에 연결합니다. description, lifecycle과 tags는 이 발췌에서 생략했습니다.

```yaml
apiVersion: bedrockagentcorecontrol.services.k8s.aws/v1alpha1
kind: AgentRuntime
metadata:
  name: {{ .Values.runtime.name | replace "_" "-" }}
  annotations:
    argocd.argoproj.io/sync-wave: "0"
    services.k8s.aws/deletion-policy: delete
spec:
  agentRuntimeName: {{ .Values.runtime.name }}
  roleARN: {{ required "runtime.roleArn is required" .Values.runtime.roleArn | quote }}
  agentRuntimeArtifact:
    containerConfiguration:
      containerURI: {{ required "runtime.imageUri is required" .Values.runtime.imageUri | quote }}
  networkConfiguration:
    networkMode: PUBLIC
  protocolConfiguration:
    serverProtocol: HTTP
  environmentVariables:
    AWS_REGION: {{ .Values.runtime.region | quote }}
    MODEL_ID: {{ .Values.runtime.modelId | quote }}
    RELEASE_VERSION: {{ .Values.runtime.release | quote }}
```

Argo CD Application에서 ECR 저장소를 별도 target으로 설정하지 않습니다. `values의 runtime.imageUri → containerURI → ACK UpdateAgentRuntime`이 배포 경로입니다. ECR에 이미지만 푸시하면 Git의 값은 바뀌지 않으므로 재배포도 일어나지 않습니다. 이 예제에는 이미지 자동 갱신 컨트롤러가 없습니다.

### Gateway 주소를 유지하며 `DEFAULT` 호출

Gateway는 `authorizerType: AWS_IAM`과 전용 실행 역할을 사용합니다. 이 HTTP 구성에서는 `protocolType`을 지정하지 않습니다. `templates/gateway.yaml`의 GatewayTarget 부분은 다음과 같습니다. description과 조건부 렌더링 구문은 생략했습니다.

```yaml
apiVersion: bedrockagentcorecontrol.services.k8s.aws/v1alpha1
kind: GatewayTarget
metadata:
  name: {{ .Values.gateway.name }}-{{ .Values.gateway.targetName }}
  annotations:
    argocd.argoproj.io/sync-wave: "2"
spec:
  name: {{ .Values.gateway.targetName }}
  gatewayIdentifierRef:
    from:
      name: {{ .Values.gateway.name }}
  targetConfiguration:
    http:
      agentcoreRuntime:
        arn: {{ required "gateway.runtimeArn is required" .Values.gateway.runtimeArn | quote }}
        qualifier: DEFAULT
  credentialProviderConfigurations:
    - credentialProviderType: GATEWAY_IAM_ROLE
```

클라이언트는 IAM SigV4로 Gateway 요청을 서명하고, Gateway는 자신의 IAM 역할로 Runtime을 호출합니다. `agent` target을 사용하면 호출 경로는 `/agent/invocations`입니다. MCP 서버의 도구 목록을 제공하는 예제와는 다른 HTTP Runtime target 구성입니다.

Runtime을 업데이트하면 새 immutable 버전이 만들어지고 `DEFAULT`가 새 버전을 가리킵니다. GatewayTarget은 동일한 Runtime ARN과 `DEFAULT`를 유지하므로, 릴리스마다 클라이언트 URL을 바꿀 필요가 없습니다. 이 동작은 [AgentCore 버전 및 endpoint 문서](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/agent-runtime-versioning.html)에 설명되어 있습니다.

### 처음에는 Runtime만 생성하기

GatewayTarget에는 생성된 Runtime의 ARN이 필요합니다. 첫 배포에서는 다음 값을 환경 파일에 명시해 Runtime만 렌더링합니다. 저장소에 이전 환경의 값이 남아 있더라도 Gateway, 분석 Job 또는 예전 endpoint가 먼저 생성되지 않도록 합니다.

```yaml
gateway:
  enabled: false
analysis:
  enabled: false
endpoint:
  enabled: false
```

다음 절에서 Application을 연결해 Runtime을 생성한 뒤 ARN과 ID를 확인합니다. 이후 아래 값을 입력하고 다시 Git에 반영하면 Gateway와 배포 후 검증이 활성화됩니다.

| 값 | 입력할 내용 |
|---|---|
| `gateway.runtimeArn` | 생성된 Runtime ARN |
| `gateway.roleArn` | CDK 출력의 `GatewayExecutionRoleArn` |
| `gateway.enabled`, `analysis.enabled` | `true` |
| `analysis.imageUri` | `gateway_probe.py`가 포함된 검증 이미지 digest |
| `endpoint.runtimeId` | 생성된 Runtime ID. 현재 코드에서 검증기 입력으로도 사용 |

`analysis.imageUri`는 검증 Job의 이미지이며 배포할 에이전트 이미지는 `runtime.imageUri`입니다. 검증 코드가 바뀌지 않았다면 검증 이미지 digest는 유지할 수 있습니다.

chart에는 이름을 지정한 `AgentRuntimeEndpoint`를 만드는 선택적 템플릿도 있습니다. `endpoint.version`은 그 endpoint가 가리킬 버전이며 Runtime 이미지를 배포하는 필드가 아닙니다. 이 글의 Gateway는 `DEFAULT`를 사용하므로 `endpoint.enabled: false`를 유지합니다. `endpoint.runtimeId`는 현재 검증기에서도 읽기 때문에 별도 endpoint를 생성하지 않아도 입력해야 합니다.

## 4. Argo CD에 Git 저장소 연결하기

다음은 Application의 source와 동기화 정책입니다. `valueFiles` 경로는 chart 디렉터리를 기준으로 해석됩니다.

```yaml
source:
  repoURL: ssh://git@github.com/YOUR_GITHUB_ORG/YOUR_REPOSITORY.git
  targetRevision: main
  path: bedrock/agentcore-gitops/charts/agentcore-agent
  helm:
    releaseName: devops-agent
    valueFiles:
      - ../../gitops/environments/dev.yaml
syncPolicy:
  automated:
    prune: true
    selfHeal: true
  syncOptions:
    - CreateNamespace=true
    - ServerSideApply=true
```

자신의 비공개 Git 저장소를 준비하고 `gitops/application.yaml`과 `gitops/project.yaml`의 저장소 주소를 함께 바꿉니다. 첫 Runtime의 이미지와 실행 역할, 비활성화 설정이 들어 있는 `gitops/environments/dev.yaml`을 검토해 커밋하고 푸시한 뒤 아래 스크립트로 연결합니다.

```bash
export GITHUB_REPOSITORY=YOUR_GITHUB_ORG/YOUR_REPOSITORY
bash scripts/configure-gitops.sh
kubectl --context eks-ack-agentcore -n argocd get application devops-agent
kubectl --context eks-ack-agentcore -n agentcore get agentruntimes -o yaml
```

Runtime 상태가 `READY`가 되면 `status.agentRuntimeID`와 `status.ackResourceMetadata.arn`을 읽습니다. 앞 절의 표에 따라 Gateway와 분석 설정을 채우고, `runtime.buildRevision`이 이미지의 빌드 식별자와 일치하는지 확인한 다음 두 번째 변경을 Git에 반영합니다. Argo CD가 Gateway와 GatewayTarget을 순서대로 생성합니다.

스크립트는 저장소 하나에 대한 읽기 전용 deploy key를 Argo CD에 설정합니다. Argo CD는 Helm을 템플릿 렌더링에 사용하고 리소스 수명주기를 직접 관리합니다. 에이전트 앱이 별도 Helm release로 `helm list`에 표시될 필요는 없습니다. 자세한 내용은 [Argo CD의 Helm 사용 방식](https://argo-cd.readthedocs.io/en/stable/user-guide/helm/)을 참고하세요.

## 5. 새 릴리스 배포와 실제 호출 검증하기

![이미지 빌드와 ECR 푸시, Git values 변경, Argo CD Pull과 ACK 업데이트를 거쳐 PostSync Gateway 검증으로 이어지는 배포 파이프라인](figures/deployment-pipeline.png)

*그림 2. GitOps 기반 릴리스의 처리 순서입니다. 이미지 빌드는 로컬 스크립트로 수행했고, 이 단계를 CI로 옮기는 것은 별도 구현 사항입니다. 지속 트래픽 측정은 PostSync Job과 별도로 실행합니다. 뒤에서 설명하는 9월 21일 재설치는 Git 변경 대신 로컬 values override를 사용했습니다.*

새 릴리스에서는 빌드 후 `gitops/environments/dev.yaml`의 `runtime.imageUri`, `release`, `buildRevision`을 바꿉니다. Pull request 리뷰와 병합을 기존 팀 절차에 연결할 수 있습니다. Argo CD는 Runtime wave 0, Gateway wave 1, GatewayTarget wave 2 순서로 동기화합니다.

```bash
bash scripts/build-agent.sh "blog-v2-$(date -u +%Y%m%dT%H%M%SZ)" blog-v2
cat .state/image-uri
```

새 digest를 `runtime.imageUri`에 넣고 `release`와 `buildRevision`을 `blog-v2`로 바꿉니다. 빌드한 이미지와 검증할 기대값을 같은 Git 변경에 담아야 합니다. 이미지 빌드만으로 배포가 시작되지는 않습니다.

배포 후 `templates/analysis.yaml`의 PostSync hook이 실행됩니다. 다음은 hook과 Job 정의의 일부입니다.

```yaml
apiVersion: argoproj.io/v1alpha1
kind: AnalysisRun
metadata:
  name: {{ .Release.Name }}-gateway-check
  annotations:
    argocd.argoproj.io/hook: PostSync
    argocd.argoproj.io/hook-delete-policy: BeforeHookCreation
spec:
  metrics:
    - name: gateway-runtime-inference
      count: 1
      failureLimit: 0
      provider:
        job:
          spec:
            backoffLimit: 1
            activeDeadlineSeconds: 660
            template:
              spec:
                serviceAccountName: gateway-check
                automountServiceAccountToken: false
                restartPolicy: Never
                nodeSelector:
                  kubernetes.io/arch: arm64
```

전체 템플릿은 검증 컨테이너에 예상 이미지, 릴리스와 빌드 식별자를 전달합니다. Job은 전용 Pod Identity로 Runtime과 `DEFAULT`의 준비 상태 및 이미지 digest를 읽고, 새 session ID로 Gateway에 요청을 보냅니다. 반환 JSON의 `release`, `build_revision`을 기대값과 대조하고 모델 응답이 비어 있지 않은지 확인합니다. 응답의 업무적 정확성을 평가하는 품질 평가 도구는 아닙니다.

앱은 `deployment_info` 도구로 릴리스 정보를 제공하며 모델에는 짧은 답변을 요청합니다. `agent/main.py`에서 모델을 설정하는 부분입니다.

```python
model_id = os.getenv("MODEL_ID", "global.anthropic.claude-sonnet-5")
model = BedrockModel(
    model_id=model_id,
    region_name=os.getenv("AWS_REGION", "us-east-1"),
    max_tokens=512,
)
```

`temperature`는 전달하지 않습니다. Runtime SDK가 `/ping`과 `/invocations`를 제공하며 이 앱은 JSON 응답을 반환합니다.

```bash
kubectl --context eks-ack-agentcore -n argocd get application devops-agent
kubectl --context eks-ack-agentcore -n agentcore get agentruntimes,gateways,gatewaytargets
kubectl --context eks-ack-agentcore -n agentcore get analysisruns,jobs,pods
bash scripts/invoke-gateway.sh
```

`Synced`는 Git 선언이 적용됐다는 뜻이고, custom health의 `Healthy`는 리소스가 준비됐다는 뜻입니다. AnalysisRun의 `Successful`과 Argo CD 작업의 `Succeeded`까지 확인한 후, 별도 호출로 기대하는 릴리스가 응답하는지도 점검합니다.

배포 순서에는 주의가 필요합니다. `DEFAULT`는 PostSync 검증 전에 새 버전으로 전환됩니다. 검증이 실패하면 Argo CD가 실패를 표시하지만 Runtime을 자동으로 이전 상태로 돌리지 않습니다. 이전 이미지 digest와 해당 릴리스의 빌드 식별자를 Git에 복원하면 이전 코드를 새 Runtime 버전으로 재배포할 수 있습니다. 새 버전을 공개하기 전에 승인받거나 트래픽을 점진적으로 이동해야 한다면 사전 검증과 승격 절차, 라우팅 방식을 별도로 설계해야 합니다.

## 배포 검증 결과

### CDK 기반 인프라 재생성

2026년 9월 21일에는 프로젝트의 기존 AgentCore 리소스와 ALB, EKS, VPC를 삭제한 후 CDK로 기반 인프라를 다시 배포했습니다. ECR 이미지는 보존하고 저장소를 새 스택에 가져왔습니다. 새 EKS의 ARM64 노드 두 대가 `Ready`가 된 뒤 Pod Identity와 플랫폼 컨트롤러를 확인했습니다.

| 확인 대상 | 결과 |
|---|---|
| CDK 기반 스택 | 생성과 CNI 권한 전환 후 `UPDATE_COMPLETE` |
| ECR | 보존된 저장소를 새 스택에 import |
| EKS | ARM64 노드 두 대 `Ready` |
| ACK | chart 1.15.1과 확장 이미지로 컨트롤러 실행 |
| Argo CD | 최종 `Synced / Healthy / Succeeded` |
| 실제 Gateway 호출 | 새 Runtime의 모델 응답과 릴리스 식별자 확인 |
| 관리용 ALB | 인증서 검증을 사용한 HTTPS 요청에 HTTP 200 |

최종 `cdk diff`에는 차이가 없었습니다. 다만 CloudFormation drift 검사에서는 노드 역할에 외부에서 추가한 `AmazonSSMManagedInstanceCore` 정책 한 건을 확인했습니다. 템플릿 비교와 실제 리소스 drift는 다른 검사이므로, 이 환경 전체가 drift 없이 일치한다고 표현하지 않습니다.

### Git 변경 기반 Runtime v7에서 v8 전환

9월 18일에는 ACK 1.15.0 기반 환경에서 Git 변경으로 Runtime을 업데이트했습니다. 상태 조회와 단발 호출만으로는 전환 중 요청을 확인할 수 없어, 별도의 `agent/rollout_probe.py` 프로세스를 먼저 시작하고 트래픽을 유지한 채 변경을 푸시했습니다. Argo CD가 성공을 보고한 뒤에도 같은 프로세스로 90초 이상 요청을 계속 보냈습니다.

2026년 9월 18일 실제 요청 구간은 15:25:15.906부터 15:28:56.154까지, 약 220초였습니다. 신규 session ID worker 두 개와 동일 session ID를 유지하는 worker 한 개를 사용했습니다. 각 worker는 응답 후 3초를 기다렸으며 최대 동시 요청은 세 개였습니다. 일정 QPS를 강제한 부하 시험은 아닙니다. 요청 timeout은 60초이고 측정 클라이언트 재시도는 껐습니다. Runtime 내부 SDK의 재시도는 변경하지 않았습니다.

| 관찰 구간 | 성공 / 요청 | 실패 | p50 지연 | p95 지연 |
|---|---:|---:|---:|---:|
| 배포 전 | 34 / 34 | 0 | 2.546초 | 3.554초 |
| 배포 중 또는 경계를 걸친 요청 | 29 / 29 | 0 | 2.592초 | 10.619초 |
| 배포 성공 관찰 후 | 43 / 43 | 0 | 2.590초 | 9.442초 |
| 전체 | 106 / 106 | 0 | 2.576초 | 9.446초 |

106건 모두 HTTP 200 응답을 받았고 timeout과 연결 reset은 관찰되지 않았습니다. Gateway ID와 URL도 유지됐습니다. 다만 배포 구간에서 p95 지연이 증가했으므로 오류율 0과 일정한 지연 시간은 구분해야 합니다. Argo CD 동기화에 걸린 약 49초도 서비스 중단 시간으로 해석하지 않습니다.

신규 세션 66건 중 26건은 v7, 이후 40건은 v8 응답을 받았습니다. 동일 세션의 40건은 계속 v7을 반환했습니다. 배포 성공 관찰 후에는 신규 세션 27건이 v8, 기존 세션 16건이 v7으로 응답했습니다. 업데이트가 처음 관찰됐을 때 처리 중이던 두 요청도 정상 완료됐습니다.

이 결과는 시험 조건에서 신규 세션 전환과 기존 세션의 버전 유지를 관찰한 것입니다. 앱은 요청마다 새 Strands Agent 객체를 만들기 때문에 같은 session ID의 버전 유지가 대화 메모리 보존을 의미하지는 않습니다. 제어 평면의 전환 시점도 주기적으로 조회한 관찰값입니다.

이번 결과는 **낮은 부하의 짧은 JSON 요청 조건에서 배포 전환 중 실패를 관찰하지 않았다**고 설명할 수 있습니다. 모든 요청의 무중단 보장이나 높은 부하, 긴 응답, SSE 스트리밍, AZ 장애 시험 결과로 확대하지 않습니다. 앞선 9월 16일 시험에서는 72건 중 Bedrock `ServiceUnavailableException` 두 건과 `MaxTokensReachedException` 네 건이 발생했습니다. v7→v8 성공이 종속 서비스와 출력 길이 관련 실패까지 해결했다는 뜻은 아닙니다.

### ACK 1.15.1 재설치 후 Runtime v1에서 v2 전환

새로 만든 EKS에 ACK 1.15.1을 설치한 뒤 Runtime version 1을 생성하고 다른 이미지 digest로 version 2를 배포했습니다. 두 배포의 PostSync AnalysisRun이 모두 성공했고, 별도의 Gateway 호출에서도 각 릴리스에 해당하는 모델 응답을 확인했습니다.

이때 단일 프로세스로 약 334초간 보낸 요청은 180/180건 성공했습니다. 배포 전 77건, 배포 중 또는 성공 관찰 경계를 걸친 55건, 성공 관찰 후 48건이며 마지막 응답까지 성공 확인 후 약 92초를 더 관찰했습니다. 신규 세션 115건은 v1 52건에서 v2 63건으로 전환됐고, 기존 세션 65건은 모두 v1을 유지했습니다. 전체 p50은 2.295초, p95는 3.691초였습니다. 이 시험도 최대 동시 요청 3개의 짧은 JSON 요청 조건입니다.

9월 21일 시험에서는 원격 Git을 변경하지 않고 Application의 `valuesObject`로 재생성된 ARN과 새 이미지를 전달했습니다. Helm 렌더링부터 Argo CD와 ACK를 거쳐 실제 호출까지의 경로를 검증한 결과입니다. 새 Git 커밋의 Pull 기반 배포를 다시 시험한 것은 아니므로 9월 18일 결과와 합산하지 않습니다.

재설치에서 발견한 CRD 충돌은 `--skip-crds`와 공통 CRD 선적용으로 수정했습니다. AWS에서 endpoint 삭제가 끝날 때까지 기다리는 처리와 이전 인증서 및 CNI 상태 파일의 보관, RETAIN ECR 재연결도 코드에 반영했습니다. 조직의 자동 관리가 추가한 GuardDuty endpoint는 프로젝트 VPC에 속한 자원임을 확인한 뒤 수동으로 정리했습니다.

## 운영 환경에 적용할 때

샘플 에이전트에는 Kubernetes 접근 도구나 인프라 변경 도구가 없습니다. Runtime 실행 역할, Gateway 실행 역할, ACK 역할과 검증 Job 역할을 분리했습니다. 하지만 Gateway가 주 호출 경로라는 사실만으로 직접 Runtime 호출이 차단되지는 않습니다. 우회 방지가 필요하면 허용할 호출 주체와 IAM 정책을 추가로 검토해야 합니다.

데모는 단일 NAT와 기본 Argo CD 구성을 사용합니다. 운영에서는 가용성 요구에 맞게 네트워크와 Argo CD를 구성하고 정식 도메인, 인증서와 SSO/RBAC를 준비해야 합니다. 오류율과 지연 시간을 감시하는 알람도 필요합니다. Global inference profile의 리전 간 라우팅은 데이터 처리 정책과 함께 검토합니다.

9월 21일 최종 이미지 스캔에는 zlib High 한 건과 Perl Untriaged 한 건이 남아 있었고, 조회 시점에 수정 버전은 없었습니다. 공개 전에 다시 스캔하고 보안 검토를 진행해야 합니다. Runtime 로그 보존 기간과 KMS 정책, ECR 이미지 보존 정책도 명시합니다. 사용 중인 Runtime 버전의 이미지가 ECR 수명주기 정책으로 삭제되지 않는지 확인하세요.

### 리소스 정리

AgentCore 리소스와 ALB가 남은 상태에서 EKS나 IAM 역할을 먼저 삭제하면 컨트롤러가 정리를 완료할 수 없습니다. 정리 스크립트는 Argo CD의 재생성을 멈춘 뒤 GatewayTarget, Gateway, 별도 endpoint, Runtime, Ingress 순서로 제거하고 컨트롤러와 CDK 기반 리소스를 삭제합니다.

```bash
CONFIRM_DESTROY=eks-ack-agentcore bash scripts/destroy.sh
```

이 스크립트는 stack/cluster 태그와 Argo CD tracking ID를 확인하고 소유한 이름만 삭제합니다. 그래도 EKS 기반 스택까지 제거하므로 전용 데모 환경에서만 그대로 사용합니다. ECR 저장소는 보존되며, 삭제된 환경의 로컬 상태는 별도 폴더로 옮깁니다. 남은 로그와 이미지, GitHub deploy key를 확인하고 조직 보안 자동화가 만든 네트워크 자원도 점검해야 합니다. 공개용 코드의 ECR 수명주기 정책은 태그 없는 이미지만 대상으로 하며, 릴리스 태그가 있는 이미지는 자동으로 만료시키지 않습니다. 이 보완은 9월 21일 실험 이후 코드 검토에서 추가했습니다.

## 마무리

ACK를 사용하면 AgentCore Runtime과 Gateway의 구성을 Kubernetes 리소스로 선언하고 기존 Argo CD 배포 흐름에 연결할 수 있습니다. 에이전트 개발자는 Git에서 이미지와 환경 설정을 변경하고, 플랫폼 팀은 익숙한 EKS 운영 도구로 적용 상태와 검증 결과를 확인합니다. 에이전트 실행은 AgentCore Runtime이 담당합니다.

도입을 검토하는 팀은 먼저 비운영 환경에서 하나의 에이전트를 연결해 보세요. `runtime.imageUri`가 실제 Runtime에 반영되는지 확인한 다음, 서비스의 요청 길이와 세션 사용 방식, 예상 부하에 맞는 시험을 추가합니다. 공개 전 승인이나 canary 전환이 필요하다면 PostSync 분석과 별도로 트래픽 승격 절차를 설계해야 합니다.

## 참고 자료

- [AgentCore Gateway HTTP Runtime targets](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/gateway-target-http-runtime.html)
- [AgentCore Runtime 버전과 endpoints](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/agent-runtime-versioning.html)
- [AgentCore Runtime HTTP protocol contract](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-http-protocol-contract.html)
- [Amazon EKS Pod Identity](https://docs.aws.amazon.com/eks/latest/userguide/pod-identities.html)
- [Argo CD Helm](https://argo-cd.readthedocs.io/en/stable/user-guide/helm/), [자동 동기화](https://argo-cd.readthedocs.io/en/stable/user-guide/auto_sync/), [Sync waves](https://argo-cd.readthedocs.io/en/stable/user-guide/sync-waves/)
- [Argo Rollouts Job metrics](https://argoproj.github.io/argo-rollouts/analysis/job/)
- [Strands Agents SDK](https://strandsagents.com/)
- [ACK AgentCore controller v1.15.1](https://github.com/aws-controllers-k8s/bedrockagentcorecontrol-controller/releases/tag/v1.15.1)
- [ACK AgentCore controller v1.15.0](https://github.com/aws-controllers-k8s/bedrockagentcorecontrol-controller/releases/tag/v1.15.0)
- [전체 Helm 코드와 설정 해설](helm-highlights.md)

# Helm chart 핵심 코드와 배포 흐름

이 문서는 [블로그 본문](article.md)의 코드 부록입니다. 경로는 별도 설명이 없으면 프로젝트 루트 기준입니다. upstream 플랫폼 chart 네 개와 로컬 애플리케이션 chart 하나를 구분합니다. 예시 계정 `123456789012`, VPC ID, ARN과 반복 문자 digest는 실제 배포 값이 아닙니다.

`snippets/`의 `*.tpl.yaml`은 렌더링 전 Helm 템플릿입니다. `kubectl apply`로 직접 적용하지 마세요. 전체 파일은 현재 소스에서 추출했고 Git 저장소 주소만 공개용 placeholder로 바꿨습니다. 본문의 짧은 YAML은 구조 설명을 위한 발췌입니다.

## 1. AWS Load Balancer Controller

Chart `aws-load-balancer-controller` 3.5.0, namespace `kube-system`. 이 chart는 관리용 ALB를 만드는 컨트롤러를 설치합니다. 애플리케이션 요청용 AgentCore Gateway를 생성하지 않습니다.

`scripts/install-platform.sh`의 설치 구문입니다. `output`과 `version`은 같은 스크립트에서 정의한 함수이므로 이 발췌만 단독 실행하지 않습니다.

```bash
helm upgrade --install aws-load-balancer-controller aws-load-balancer-controller \
  --repo https://aws.github.io/eks-charts --version "$(version loadBalancerControllerChart)" \
  --kube-context "$KUBE_CONTEXT" --namespace kube-system \
  --set clusterName="$CLUSTER_NAME" --set region="$AWS_REGION" --set vpcId="$(output VpcId)" \
  --set serviceAccount.name=aws-load-balancer-controller --wait --timeout 10m
```

같은 값을 [values 예시](snippets/load-balancer-values.example.yaml)로 정리했습니다. ServiceAccount 이름은 CDK의 Pod Identity association과 일치해야 합니다. Ingress는 chart의 일부로 넣지 않고 `scripts/render-ingress.py`가 생성합니다. 주요 annotation은 다음과 같습니다. ARN과 CIDR은 교체용 문자열입니다.

```yaml
alb.ingress.kubernetes.io/scheme: internet-facing
alb.ingress.kubernetes.io/target-type: ip
alb.ingress.kubernetes.io/listen-ports: '[{"HTTPS":443}]'
alb.ingress.kubernetes.io/certificate-arn: YOUR_ACM_CERTIFICATE_ARN
alb.ingress.kubernetes.io/inbound-cidrs: YOUR_ADMIN_PUBLIC_IP/32
alb.ingress.kubernetes.io/backend-protocol: HTTPS
alb.ingress.kubernetes.io/healthcheck-protocol: HTTPS
alb.ingress.kubernetes.io/healthcheck-path: /healthz
```

## 2. Argo CD

Chart `argo-cd` 10.9.0, app v3.5.2, namespace `argocd`.

```bash
helm upgrade --install argocd argo-cd --repo https://argoproj.github.io/argo-helm \
  --version "$(version argoCdChart)" --kube-context "$KUBE_CONTEXT" --namespace argocd --create-namespace \
  --values config/argocd-values.yaml --wait --timeout 10m
```

기본 설정은 다음과 같습니다. 전체 Lua health check는 [argocd-values.yaml](snippets/argocd-values.yaml)에 있습니다.

```yaml
configs:
  params:
    server.insecure: false
  cm:
    timeout.reconciliation: 30s
    timeout.reconciliation.jitter: 5s
    resource.customizations.health.argoproj.io_AnalysisRun: |
      local phase = obj.status and obj.status.phase or "Pending"
      if phase == "Successful" then return {status = "Healthy", message = phase} end
      if phase == "Failed" or phase == "Error" or phase == "Inconclusive" then
        return {status = "Degraded", message = phase}
      end
      return {status = "Progressing", message = phase}
dex:
  enabled: false
notifications:
  enabled: false
server:
  ingress:
    enabled: false
```

`server.insecure: false`와 별도 Ingress의 HTTPS backend 설정을 함께 유지합니다. chart 자체 Ingress는 꺼져 있습니다. `dex.enabled: false`인 이 데모는 SSO가 완성된 운영 구성이 아닙니다. poll 간격 30초와 jitter 5초는 설정값이며 모든 변경이 35초 이내 배포된다는 보장은 아닙니다.

Runtime, Gateway, GatewayTarget의 health check는 `ACK.Terminal`, `ACK.ResourceSynced`, AWS `READY` 상태를 읽습니다. AnalysisRun health는 Job 분석 결과를 읽습니다. 이 설정 덕분에 AWS 리소스 준비와 검증 결과가 Argo CD에 표시되지만, Argo CD 화면에 EKS 에이전트 Pod가 생기는 것은 아닙니다.

## 3. ACK AgentCore controller

현재 설치 설정은 chart `bedrockagentcorecontrol-chart` 1.15.1, 확장 이미지 `1.15.1-http-runtime.1`, namespace `agentcore`입니다. 9월 21일 전체 재설치와 실제 호출을 확인했으며 본문의 106건 시험은 이전 1.15.0 기반 기록입니다. Runtime 자체는 upstream 지원이며 HTTP Runtime target 확장과 endpoint 업데이트 보정은 유지합니다.

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
resources:
  requests:
    cpu: 100m
    memory: 128Mi
  limits:
    memory: 512Mi
```

이는 [ack-values.yaml](snippets/ack-values.yaml) 전체입니다. 컨트롤러의 AWS 권한은 CDK 역할에 있으며 Helm values에는 자격증명이 없습니다. 설치 스크립트는 AWS 또는 Kubernetes 변경 전에 `scripts/ack-assets.py`로 이미지 digest, chart와 컨트롤러 버전, 소스 commit과 CRD 일곱 개의 해시를 검사합니다. 서비스 CRD 네 개 외에 AdoptedResource, FieldExport, IAMRoleSelector가 포함됩니다. `ACK_IMAGE_VALUES`를 지정하면 기본 `.state/ack-image-values.json`보다 우선합니다.

아래는 플랫폼 설치 스크립트의 CRD 적용과 chart 설치 부분입니다. `kube`와 `version`은 스크립트 함수이고 `ack_image_values`는 사용자 빌드의 이미지 override 파일입니다.

```bash
test -f .state/ack-crds/bedrockagentcorecontrol.services.k8s.aws_gateways.yaml
kube apply --server-side --field-manager=ack-http-schema --force-conflicts -f .state/ack-crds/
helm upgrade --install ack-agentcore oci://public.ecr.aws/aws-controllers-k8s/bedrockagentcorecontrol-chart \
  --version "$(version ackAgentCoreChart)" --kube-context "$KUBE_CONTEXT" --namespace agentcore --create-namespace --skip-crds \
  --values config/ack-values.yaml --values "$ack_image_values" --set aws.region="$AWS_REGION" --wait --timeout 10m
```

`--force-conflicts`는 소유 필드를 가져오는 옵션이므로 기존 공용 클러스터의 CRD에 그대로 적용하기 전에 필드 소유권과 호환성을 검토해야 합니다. Helm chart 업그레이드만으로 이미 설치한 CRD가 자동 갱신된다고 가정하지 않습니다. 또한 fresh install에서도 `--skip-crds`가 없으면 Helm 4가 stock Gateway CRD를 다시 적용해 확장 스키마와 충돌할 수 있습니다. 필요한 공통 CRD까지 사전에 설치하는 이유입니다.

패치는 HTTP Runtime target의 ARN과 qualifier를 생성, 조회, 갱신 API에 연결하고 desired/observed 비교에 반영합니다. 별도 endpoint 업데이트의 이름과 관찰 버전 처리 보정도 포함합니다. 빌드 스크립트는 endpoint 세 개와 HTTP target 세 개의 회귀 테스트를 포함합니다. 최신 upstream 버전으로 이전할 때도 CRD와 컨트롤러 이미지를 한 쌍으로 검증해야 합니다.

## 4. Argo Rollouts

Chart `argo-rollouts` 2.43.1, app v1.10.0, namespace `argo-rollouts`.

```bash
helm upgrade --install argo-rollouts argo-rollouts --repo https://argoproj.github.io/argo-helm \
  --version "$(version argoRolloutsChart)" --kube-context "$KUBE_CONTEXT" --namespace argo-rollouts --create-namespace \
  --set dashboard.enabled=false --wait --timeout 10m
```

이 설치 구문을 [rollouts-values.yaml](snippets/rollouts-values.yaml)에도 정리했습니다. 중요한 배포 정책은 아래 로컬 chart의 `AnalysisRun`에 있습니다. 이 구성은 독립적인 Job 분석이며 `Rollout.spec.strategy.blueGreen`, `canary`, 서비스 selector 전환을 사용하지 않습니다.

## 5. 로컬 `agentcore-agent` chart

### Chart.yaml과 values 병합

```yaml
apiVersion: v2
name: agentcore-agent
description: Manage a Strands AgentCore Runtime and stable endpoint through ACK
type: application
version: 0.1.0
appVersion: "v1"
```

chart의 `version`과 `appVersion`은 chart metadata입니다. AWS Runtime 버전은 ACK의 AWS API 업데이트 결과로 생성됩니다. 기본 `values.yaml` 위에 환경별 `gitops/environments/dev.yaml`이 덮어써집니다. 공개용 전체 값은 [dev-values.example.yaml](snippets/dev-values.example.yaml)에 있습니다.

| 값 | 사용 위치 | 주의점 |
|---|---|---|
| `runtime.imageUri` | Runtime의 `containerURI` | 새 에이전트 배포 입력. ECR digest 권장 |
| `runtime.roleArn` | Runtime 실행 역할 | CDK 출력의 `ExecutionRoleArn` |
| `runtime.modelId` | 컨테이너 `MODEL_ID` | 검증한 Global inference profile |
| `runtime.release` | `RELEASE_VERSION` 및 검증 기대값 | AWS 버전 번호 지정 필드 아님 |
| `runtime.buildRevision` | 검증의 `--expect-build` | Docker `BUILD_REVISION`과 일치해야 함 |
| `gateway.runtimeArn` | HTTP Runtime target ARN | 최초 Runtime 생성 후 입력 |
| `analysis.imageUri` | 검증 Job의 `image` | Runtime 이미지와 다른 역할 |
| `endpoint.runtimeId` | 검증기 및 선택적 endpoint | endpoint 비활성 상태에서도 분석에 필요 |
| `endpoint.version` | 선택적 named endpoint의 버전 | Gateway의 `DEFAULT`와 무관 |

### Runtime template

[runtime.tpl.yaml](snippets/runtime.tpl.yaml)은 전체 템플릿입니다. 핵심 연결과 세션 제한은 다음과 같습니다.

```yaml
agentRuntimeArtifact:
  containerConfiguration:
    containerURI: {{ required "runtime.imageUri is required" .Values.runtime.imageUri | quote }}
networkConfiguration:
  networkMode: PUBLIC
protocolConfiguration:
  serverProtocol: HTTP
lifecycleConfiguration:
  idleRuntimeSessionTimeout: 300
  maxLifetime: 3600
```

idle timeout과 최대 수명은 각각 초 단위입니다. 영속 대화 메모리 설정이 아닙니다. `PUBLIC` 네트워크 모드도 익명 호출 허용이라는 뜻은 아닙니다. 호출 인증과 실행 네트워크 설정은 구분합니다.

### Gateway와 Target template

[gateway.tpl.yaml](snippets/gateway.tpl.yaml)은 두 Kubernetes 리소스를 렌더링합니다. Gateway는 wave 1에 생성합니다.

```yaml
apiVersion: bedrockagentcorecontrol.services.k8s.aws/v1alpha1
kind: Gateway
metadata:
  name: {{ .Values.gateway.name }}
  annotations:
    argocd.argoproj.io/sync-wave: "1"
spec:
  name: {{ .Values.gateway.name }}
  description: HTTP entry point for the GitOps-managed AgentCore Runtime
  authorizerType: AWS_IAM
  roleARN: {{ required "gateway.roleArn is required" .Values.gateway.roleArn | quote }}
  tags:
    Project: eks-ack-agentcore
    ManagedBy: argocd-ack
```

GatewayTarget은 wave 2에서 다음 설정을 사용합니다.

```yaml
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

`gatewayIdentifierRef`는 Kubernetes Gateway 이름을 참조합니다. Runtime ARN은 이 템플릿에서 자동 참조하지 않고 values로 받습니다. HTTP target 스키마는 앞에서 설명한 ACK 확장 패치에 의존합니다.

### PostSync AnalysisRun template

[analysis.tpl.yaml](snippets/analysis.tpl.yaml)은 ServiceAccount와 AnalysisRun을 렌더링합니다. hook은 매 동기화 때 이전의 같은 이름 hook을 제거하고 새로 생성합니다. 이 때문에 단일 AnalysisRun 객체를 장기 이력 저장소로 사용하지 않습니다.

```yaml
metadata:
  name: {{ .Release.Name }}-gateway-check
  annotations:
    argocd.argoproj.io/hook: PostSync
    argocd.argoproj.io/hook-delete-policy: BeforeHookCreation
```

Job 컨테이너에 전달하는 인수는 다음과 같습니다.

```yaml
containers:
  - name: verify
    image: {{ required "analysis.imageUri is required" .Values.analysis.imageUri | quote }}
    command: [python, /app/gateway_probe.py]
    args:
      - --gateway-name
      - {{ .Values.gateway.name | quote }}
      - --target
      - {{ .Values.gateway.targetName | quote }}
      - --runtime-id
      - {{ .Values.endpoint.runtimeId | quote }}
      - --expect-release
      - {{ .Values.runtime.release | quote }}
      - --expect-image
      - {{ .Values.runtime.imageUri | quote }}
      - --expect-build
      - {{ .Values.runtime.buildRevision | quote }}
```

Job은 `gateway-check` ServiceAccount, ARM64 node selector와 non-root UID 10001을 사용합니다. 컨테이너 권한 상승을 막고 Linux capability를 모두 제거합니다. `count: 1`은 분석 측정 한 번이며, `backoffLimit: 1` 때문에 실패 시 Job 재시도가 가능합니다. 지속 트래픽 시험의 “클라이언트 재시도 0회”와 혼동하지 않습니다.

검증기는 control-plane 준비 상태와 이미지 digest를 기다린 후 실제 Gateway 호출을 수행합니다. JSON의 릴리스 이름과 빌드 식별자가 기대값과 일치하는지, 모델 응답이 비어 있지 않은지 확인합니다. `DEFAULT`가 이미 새 버전으로 전환된 뒤 실행하므로 사전 승인 gate가 아닙니다. 실패 결과를 기록하지만 자동 rollback은 하지 않습니다.

### 선택적 named endpoint template

[endpoint.tpl.yaml](snippets/endpoint.tpl.yaml)은 이전 실험과 named endpoint 사용을 위해 남아 있습니다.

```yaml
spec:
  agentRuntimeID: {{ required "endpoint.runtimeId is required" .Values.endpoint.runtimeId | quote }}
  agentRuntimeVersion: {{ .Values.endpoint.version | quote }}
  name: {{ .Values.endpoint.name }}
  description: Stable endpoint with a Git-pinned AgentCore version
```

본문의 Gateway 경로는 이 endpoint를 사용하지 않습니다. 예시 values는 `endpoint.enabled: false`이며, `endpoint.version: "2"`는 비활성 상태에서 렌더링되지 않습니다. 이 값만 바꿔도 Runtime 이미지가 배포되는 것으로 설명해서는 안 됩니다.

## Application과 AppProject

이 둘은 upstream Helm chart가 아닌 Argo CD 선언입니다. 전체 공개용 파일은 [application.yaml](snippets/application.yaml)과 [project.yaml](snippets/project.yaml)에 있습니다.

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

AppProject의 허용 저장소와 Application 저장소 주소를 함께 수정합니다. destination은 `agentcore` 네임스페이스이고 허용 리소스 범위는 AppProject에서 확인합니다. Argo CD의 자동 prune을 켰으므로 리소스 삭제도 배포 변경에 포함됩니다. `deletion-policy: delete`를 지정한 Runtime 선언을 Git에서 제거하면 실제 AWS 리소스 삭제로 이어질 수 있습니다.

## 로컬 확인

아래 명령은 렌더링과 구문 확인이며 AWS 배포나 실제 호출 검증은 아닙니다.

```bash
helm lint charts/agentcore-agent \
  -f docs/aws-tech-blog/snippets/dev-values.example.yaml
helm template devops-agent charts/agentcore-agent --namespace agentcore \
  -f docs/aws-tech-blog/snippets/dev-values.example.yaml
```

예시에서는 ServiceAccount, AgentRuntime, Gateway, GatewayTarget, PostSync AnalysisRun이 렌더링됩니다. 별도 `AgentRuntimeEndpoint`와 `Rollout`은 렌더링되지 않습니다.

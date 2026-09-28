# AWS Tech Blog 발행 에셋

대상 독자는 Amazon EKS와 Argo CD를 운영하는 플랫폼 엔지니어입니다. 기업의 AI 에이전트 개발 수요와 기존 EKS 및 GitOps 표준을 연결하는 배경으로 원고를 시작하고, CDK 구축부터 실제 호출 검증까지 안내합니다. 한국어 원고에 humanizer 스킬의 편집 절차를 적용했습니다. 본문, 코드 부록, 도식과 캡션에는 em dash 및 middle dot을 사용하지 않습니다. 과장된 도입 효과와 검증되지 않은 무중단 보장은 제외했습니다.

## 파일 안내

| 파일 | 용도 |
|---|---|
| [article.md](article.md) | 블로그 본문. 발행 시 사용할 단일 원고 |
| [helm-highlights.md](helm-highlights.md) | upstream chart 네 개와 로컬 chart의 코드 부록 |
| [architecture.png](figures/architecture.png) | 그림 1, 배포 아키텍처 |
| [architecture.drawio](figures/architecture.drawio) / [SVG](figures/architecture.svg) | 그림 1 편집 원본과 벡터 이미지 |
| [deployment-pipeline.png](figures/deployment-pipeline.png) | 그림 2, 이미지 빌드부터 실제 호출 검증까지 |
| [deployment-pipeline.drawio](figures/deployment-pipeline.drawio) / [SVG](figures/deployment-pipeline.svg) | 그림 2 편집 원본과 벡터 이미지 |
| [snippets/dev-values.example.yaml](snippets/dev-values.example.yaml) | 계정, ARN과 digest를 대체한 전체 values 예시 |
| [tools/build_assets.py](tools/build_assets.py) | native draw.io XML과 소스 발췌 생성 |
| [tools/render.sh](tools/render.sh) | draw.io Desktop으로 PNG/SVG 내보내기 |

`.drawio` 파일의 도형과 문구, 연결선을 draw.io에서 각각 편집할 수 있습니다. PNG/SVG에도 diagram 데이터를 포함했습니다. ECR, Bedrock, CloudWatch는 draw.io의 AWS resource icon을 사용하고 AgentCore는 논리적 구성 요소 상자로 표시했습니다.

공개용 예시의 계정 `123456789012`, ARN, VPC ID, 반복 문자 digest는 배포에 사용할 수 없는 placeholder입니다. `*.tpl.yaml`은 Helm 템플릿이므로 `kubectl apply`에 직접 전달하지 않습니다. 이 폴더에는 문서와 이미지를 모았으며 배포 소스 전체를 대신하지 않습니다.

## 그림 설명과 대체 텍스트

### 그림 1

캡션: 기존 EKS의 Argo CD와 ACK가 AgentCore를 관리하는 배포 아키텍처. 관리용 ALB와 에이전트 호출 경로를 분리하고, 실제 요청은 Gateway에서 Runtime과 Bedrock으로 전달한다.

대체 텍스트: Git의 Helm 선언을 EKS의 Argo CD가 적용하고 ACK가 AWS AgentCore 리소스를 조정한다. Argo Rollouts Job은 Gateway를 호출해 배포를 검사한다. 애플리케이션 요청은 IAM SigV4로 Gateway에 들어와 Runtime DEFAULT와 Bedrock Global 모델을 호출한다.

읽는 법: 파랑은 관리와 배포, 초록은 요청, 주황은 이미지, 보라는 로그 경로입니다. NAT, VPC endpoint와 관리자에서 EKS API로 가는 선은 생략했습니다. EKS 기반 리소스와 관리용 ALB는 고객 VPC에 있으며 AgentCore는 관리형 서비스입니다. Global 모델 추론을 `us-east-1`에 고정한다는 의미가 아닙니다.

### 그림 2

캡션: ARM64 이미지 빌드, ECR digest 기록, Git 변경, Argo CD Pull, ACK Runtime 업데이트와 PostSync 실제 호출 검증으로 이어지는 파이프라인.

대체 텍스트: 첫 줄에서 코드 검증과 이미지 빌드 후 ECR에 푸시하고 Git values를 변경한다. 둘째 줄에서 Argo CD가 Git을 읽고 ACK가 Runtime을 업데이트한다. DEFAULT 전환 후 셋째 줄의 AnalysisRun이 Gateway를 호출해 성공 또는 실패를 보고한다. 자동 Runtime rollback은 없다.

읽는 순서: 첫 줄은 왼쪽에서 오른쪽, 둘째 줄은 오른쪽에서 왼쪽, 셋째 줄은 왼쪽에서 오른쪽입니다. 검증한 빌드는 로컬 스크립트였으며 CI로 확장 가능한 단계만 표시했습니다. 그림 아래 지속 트래픽 시험은 PostSync 검증 Job과 별도입니다.

## 사실 확인 범위

본문에는 9월 18일 Git 변경 기반 106/106 기록과 9월 21일 전체 재설치 후 180/180 기록을 별도로 담았습니다. 9월 21일에는 AWS 자원을 삭제한 후 다시 생성했지만 Git commit/push는 하지 않았고 Argo CD `valuesObject`를 사용했습니다. 두 시험의 배포 입력 방식과 표본 범위를 혼동하지 않습니다. 상세 증거는 저장소의 `docs/clean-redeployment-2026-09-21.md`에 있습니다. 이번 문서 편집에서는 기록과 코드를 대조했으며 AWS 자원을 변경하거나 시험을 다시 실행하지 않았습니다.

| 본문 내용 | 저장소 근거 |
|---|---|
| 인프라, 역할, Pod Identity, 네트워크 | `infra/platform-stack.ts` |
| 검증 버전 | `config/versions.json`, `package.json`, `agent/pyproject.toml` |
| 플랫폼 chart 설치와 CRD 선적용 | `scripts/install-platform.sh` |
| ARM64 빌드와 digest | `scripts/build-agent.sh`, `agent/Dockerfile` |
| Runtime/Gateway/검증 템플릿 | `charts/agentcore-agent/templates/` |
| ECR→values→Application 연결 | `gitops/application.yaml`, `gitops/environments/dev.yaml` |
| 실제 Gateway 검증 범위 | `agent/gateway_probe.py` |
| 요청별 세션과 지속 트래픽 | `agent/rollout_probe.py` |
| 106/106 통계와 구간 정의 | `.state/continuous-v7-v8-20260918T062029Z/traffic-summary.json`, `validation-summary.json` |
| 앞선 실패와 보완 과제 | `docs/continuity-check-2026-09-16.md`, `docs/full-verification-2026-09-16.md` |
| v7→v8 상세 기록 | `docs/continuous-deployment-2026-09-18.md` |
| ACK 확장 범위 | `patches/ack-controller/README.md`, `scripts/build-ack-controller.sh` |

원본 `.state`와 운영 기록에는 실제 계정과 접속 정보가 포함될 수 있습니다. 발행 패키지에는 넣지 않고 필요한 통계만 본문에 옮겼습니다. 발행자는 계정 식별자가 있는 운영 보고서를 그대로 첨부하지 않아야 합니다.

### 9월 21일 upstream 확인

- [ACK v1.15.1 release](https://github.com/aws-controllers-k8s/bedrockagentcorecontrol-controller/releases/tag/v1.15.1)는 2026-09-18 17:00:10 UTC에 공개됐습니다. 본문의 9월 18일 KST 시험보다 뒤입니다.
- [v1.15.1 types.go](https://github.com/aws-controllers-k8s/bedrockagentcorecontrol-controller/blob/v1.15.1/apis/v1alpha1/types.go)의 `TargetConfiguration`에는 확인 시점에 `Mcp`만 있습니다. 본문의 HTTP target을 stock chart에서 지원한다고 설명하지 않습니다.
- 9월 21일 chart 1.15.1과 확장 빌드 `1.15.1-http-runtime.1`로 전체 재설치를 수행하고 실제 호출 및 Runtime v1→v2 전환을 확인했습니다. 이 시험은 180/180이며 local values override를 사용했습니다. 본문의 106/106 결과는 9월 18일 1.15.0 기반 실험입니다. 아키텍처 도식은 1.15.1 구성을 표시하고 파이프라인 도식은 GitOps의 목표 배포 흐름과 두 시험의 차이를 설명합니다.
- AgentCore [HTTP Runtime target](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/gateway-target-http-runtime.html), [versioning](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/agent-runtime-versioning.html), Argo CD [Helm](https://argo-cd.readthedocs.io/en/stable/user-guide/helm/), Argo Rollouts [Job](https://argoproj.github.io/argo-rollouts/analysis/job/) 문서와 대조했습니다.

## 발행 전 체크리스트

- [ ] 저자, 기술 검토자, 게시 가능한 소스 저장소 URL을 확정하고 `YOUR_GITHUB_ORG/YOUR_REPOSITORY`를 바꿉니다. 현 저장소 전체를 공개할 권한이 부여된 것은 아닙니다.
- [ ] 본문과 코드 부록 중 실제 게시할 범위를 정합니다. 별도 코드 부록을 게시하지 않으면 링크를 공개 소스로 교체합니다.
- [ ] 계정별 값과 private repo 기본값을 제거한 별도 공개용 소스 사본에서 처음부터 재현합니다. 현재 패키지는 발췌만 익명화했습니다.
- [ ] 공식 ACK 지원 여부를 다시 확인합니다. 확장 패치를 유지한다면 지원 범위와 자체 유지보수 책임을 명시하고 소스와 회귀 테스트를 공개 가능한 형태로 준비합니다.
- [ ] 모델 사용 가능 리전과 권한, Global inference profile의 데이터 처리 정책을 재확인합니다.
- [ ] 이미지 보안 스캔을 다시 수행하고 남아 있는 zlib High 항목의 수정 또는 예외 판단을 기록합니다. 이번 문서 작업으로 해결한 항목이 아닙니다.
- [ ] Runtime 로그 retention/KMS, ECR 이미지 보존, 운영 HA, SSO/RBAC, 알람과 비용 정책을 정합니다. 단일 NAT와 자체 서명 30일 인증서는 데모 조건입니다.
- [ ] 기록된 노드 역할의 외부 `AmazonSSMManagedInstanceCore` 정책 drift는 소유권을 확인한 후 처리합니다. 문서 작성 중 임의 수정하지 않았습니다.
- [ ] `DEFAULT` 전환이 PostSync보다 먼저 발생한다는 설명과 자동 rollback 미구현을 유지합니다.
- [ ] 106/106과 180/180을 전체 서비스의 무중단 보장으로 표현하지 않고 시험 시간, 부하, 세션과 지연 수치를 함께 게시합니다. 9월 21일 결과는 새 Git 커밋의 Pull 배포 검증이 아님을 명시합니다.
- [ ] 새 ARN이 있는 환경 values를 검토하고 푸시한 뒤 Argo CD의 local values override를 제거하고 Git-only 최종 검증을 수행합니다. 푸시 전에 override를 제거하면 원격의 이전 ARN이 적용됩니다.
- [ ] 그림 캡션과 대체 텍스트를 CMS에도 입력합니다. 삽입 폭에서 글자 가독성을 확인하고 필요하면 SVG 또는 확대 이미지를 제공합니다.
- [ ] 공개할 파일에서 실제 계정, Gateway/ALB 주소, 관리자 CIDR, 암호, private key와 kubeconfig가 없는지 최종 확인합니다.

## 에셋 재생성

문서 작업에서 로컬 `helm lint`와 `helm template`을 실행해 통과했습니다. 템플릿 다섯 리소스의 image digest, `DEFAULT`, PostSync 연결을 확인했고, 코드 발췌 원본 대조, YAML 파싱, 상대 링크, draw.io XML 및 PNG 육안 검사를 수행했습니다. 실험 표의 모든 요청 수와 p50/p95는 원본 JSON과 대조했습니다. 이 검사는 AWS 재배포와 실제 호출을 대체하지 않습니다.

프로젝트 루트에서 실행합니다. draw.io Desktop 29.3.0과 Python 3으로 생성했습니다.

```bash
bash docs/aws-tech-blog/tools/render.sh
```

다른 OS 또는 설치 경로에서는 `DRAWIO_BIN`을 지정합니다.

```bash
DRAWIO_BIN=/path/to/drawio bash docs/aws-tech-blog/tools/render.sh
```

스크립트는 XML과 snippets를 소스에서 다시 생성한 뒤 PNG/SVG를 내보냅니다. draw.io에서 수동 편집한 결과를 유지하려면 파일을 다른 이름으로 저장하거나 해당 변경을 `build_assets.py`에 반영하세요. 생성 스크립트를 다시 실행하면 기본 파일의 수동 편집은 덮어씁니다. 한글 렌더링에는 `Apple SD Gothic Neo`를 사용했으며 다른 OS에서는 사용 가능한 한글 글꼴로 `FONT`를 바꿉니다.

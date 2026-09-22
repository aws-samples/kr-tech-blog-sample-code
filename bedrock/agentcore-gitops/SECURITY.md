# 공개 전 보안 검토

이 샘플은 비운영 전용 계정에서 사용하는 기술 예제입니다. 공개 소스의 검토와 이를 배포하는 환경의 운영 보안은 별개입니다. 자동 검사 통과가 AWS의 보안 승인이나 모든 취약점 부재를 보증하지 않습니다.

## 포함하지 않는 정보

배포 계정의 ID와 ARN, 실제 Runtime ID, 개인 저장소 주소, EKS context, 인증서, private key, 관리자 비밀번호, `.state/`, 계정별 `cdk.context.json`, CloudFormation 출력과 과거 운영 로그는 공개 배포물에서 제외합니다. Git 이력 전체를 복사하지 않고 선택한 소스만 새 디렉터리에 넣습니다.

초기 `gitops/environments/dev.yaml`의 이미지 URI와 실행 역할은 비어 있으며 Gateway와 분석은 비활성화되어 있습니다. 자신의 계정에서 이미지를 빌드하고 값을 채워야 합니다. `docs/aws-tech-blog/snippets`의 계정과 digest는 설명용 placeholder입니다.

`.state`는 `umask 077` 및 디렉터리 권한 700으로 생성합니다. Git deploy key는 권한 600을 사용합니다. 소스의 `.gitignore`는 key, 환경 변수 파일과 빌드 산출물을 제외하지만, 사용자가 강제로 추가한 파일까지 보호하지는 못하므로 커밋 전에 secret scan이 필요합니다.

## 구현된 제한

- 관리 ALB와 EKS API는 명시한 IPv4 /32 CIDR만 허용합니다. Gateway의 요청은 IAM SigV4 서명이 필요합니다.
- Pod Identity, ACK 역할, Gateway 역할과 Runtime 실행 역할을 구분합니다. 정적 AWS access key를 Kubernetes에 넣지 않습니다.
- AgentCore 실행 역할은 지정한 모델과 프로젝트 Runtime 범위의 권한을 사용합니다. `PassRole`은 지정한 실행 역할로 제한합니다.
- 에이전트는 non-root ARM64 이미지로 실행하며 인프라 변경 도구나 Kubernetes 접근 도구를 제공하지 않습니다.
- Gateway 검증기는 HTTPS AWS Gateway 호스트만 허용하고 HTTP redirect를 따라가지 않습니다.
- 이미지 digest와 패치 소스 commit을 고정합니다. ACK 설치 전 CRD 일곱 개와 빌드 metadata를 확인합니다.
- ECR 수명주기 정책은 태그 없는 이미지만 만료시킵니다. 사용 중인 릴리스와 컨트롤러 태그를 자동 삭제하지 않습니다.
- 삭제 스크립트는 프로젝트 태그와 Argo CD tracking ID를 확인한 뒤 지정된 리소스를 정리합니다.

## 공개 승인 전에 남은 항목

2026-09-22 수행한 자동 검사의 결과는 다음과 같습니다. 서로 다른 검사 목적을 합쳐 하나의 보안 승인으로 해석하지 않습니다.

| 검사 | 결과와 범위 |
|---|---|
| Gitleaks 8.30.1 | 원본 Git 이력 19개 commit과 공개 후보에서 secret 탐지 0건 |
| npm audit | lockfile 기준 알려진 취약점 0건 |
| pip-audit 2.10.1 | Runtime requirements의 패키지 50개에서 알려진 취약점 0건 |
| Bandit 1.9.4 | Medium/High 0건. 로컬 Git 경로 조회의 subprocess 사용 관련 Low 3건 |
| IAM Access Analyzer | 기존 배포의 inline identity policy 7개에서 finding 0건 |
| cdk-nag 3.0.2 | CDK 리소스 52개 검사. 21개 finding 그룹, 리소스 기준 29건. 통과 아님 |

cdk-nag의 항목은 `AwsSolutions-EKS1`, `AwsSolutions-IAM4`, `AwsSolutions-IAM5`입니다. 각각 공개 EKS API endpoint, AWS managed policy 사용, wildcard 권한과 관련됩니다. 공개 endpoint는 관리자 /32로 제한되고 일부 wildcard는 서비스 생성 API에 필요하지만, 그 사실만으로 검토가 끝나지는 않습니다. 허용 범위를 더 줄일지 또는 데모의 명시적 예외로 인정할지 검토해야 합니다. 결과를 숨기기 위해 suppression을 추가하지 않았습니다.

Bandit Low 항목은 고정 인수 배열로 Git 루트를 조회하는 로컬 subprocess이며 `shell=True`나 원격 입력 문자열 실행을 사용하지 않습니다. 신뢰할 수 있는 개발 환경의 PATH가 전제입니다. 실행 환경의 위험까지 제거했다는 의미는 아닙니다.

2026-09-22 재조회한 기존 배포 이미지에는 수정 버전이 없는 zlib High 한 건과 Perl Untriaged 한 건이 있습니다. 공개 전에 최신 스캔 결과를 검토하고 보안 담당자의 판단에 따라 수정 또는 예외 처리를 기록해야 합니다. 이 문서는 해당 항목의 예외 승인이 아닙니다.

공식 ACK에 없는 HTTP Runtime target은 자체 확장 패치입니다. upstream 업데이트에 따른 지원 여부, 패치 코드와 컨테이너 이미지의 유지보수 책임을 명시해야 합니다. [외부 소스 고지](THIRD-PARTY.md)에 ACK와 ALB controller 정책의 출처를 적고 upstream LICENSE 및 NOTICE를 포함했습니다. 상위 저장소 MIT-0으로 외부 코드를 재선언하지 않습니다. 라이선스 고지 보존은 보안 승인이나 법률 검토 완료를 뜻하지 않습니다.

공개 monorepo 경로로 변환한 사본은 정적 검사와 Helm 렌더링을 검증하더라도 새 Git 커밋으로 배포한 증거가 자동으로 생기지 않습니다. 대상 경로가 포함된 자신의 저장소에서 Git-only 신규 배포 및 정리 검증을 마쳐야 합니다.

검사 당시 기존 Runtime은 `READY`였고 실제 모델 호출은 성공했습니다. 그러나 공인 egress IP가 기존 EKS 허용 목록과 달라 kubectl 최신 상태 조회는 timeout으로 끝났습니다. 이번 점검에서는 허용 목록이나 클러스터를 변경하지 않았으며 Kubernetes 상태 재검증을 완료했다고 표현하지 않습니다.

## 운영 환경의 추가 보완

- 자체 서명 30일 인증서와 초기 Argo CD admin은 데모 설정입니다. 정식 인증서, SSO와 최소 권한 RBAC로 교체하세요.
- Runtime 로그의 보존 기간과 KMS 설정을 요구사항에 맞게 적용합니다. EKS와 VPC flow logs의 암호화와 보존 정책도 별도 검토 대상입니다.
- 단일 NAT와 기본 Argo CD 구성은 운영 HA를 의미하지 않습니다. 오류율, 지연 시간과 비용 알람을 추가하세요.
- IAM의 생성 및 일부 목록 API에는 wildcard가 남아 있습니다. ARN을 만들기 전 검사, workload identity 및 endpoint 생성 범위를 포함하므로 정책을 사용 환경에 맞게 리뷰해야 합니다.
- Gateway를 통하지 않는 Runtime 직접 호출을 완전히 차단한 구성은 아닙니다. Gateway-only 정책이 필요하면 호출 주체를 추가로 제한합니다.
- Global inference profile은 다른 리전에서 추론할 수 있으므로 데이터 처리 정책을 먼저 확인합니다.
- 실험 환경에는 노드 역할에 외부 추가된 SSM 정책 drift가 있습니다. 소유자를 확인하지 않고 삭제하지 않습니다.
- 조직 GuardDuty가 자동 생성한 VPC endpoint가 스택 삭제를 막을 수 있습니다. 해당 VPC의 소유권과 용도를 확인한 후 처리하며 계정 전체 GuardDuty를 끄지 않습니다.

보안 취약점은 상위 `CONTRIBUTING.md`의 비공개 신고 절차를 사용하며 공개 issue에 자격증명이나 공격 가능한 정보를 올리지 않습니다.

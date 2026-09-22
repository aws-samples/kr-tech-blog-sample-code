# 검증 범위와 배포 상태

이 폴더는 공개 monorepo `bedrock/agentcore-gitops` 경로에 맞춘 제출 후보입니다. 소스 검사, 실제 AWS 배포 기록, 새로운 monorepo 사본의 배포는 구분합니다.

## 기존 코드의 실배포 기록

2026-09-21 기존 프로젝트를 삭제한 후 CDK로 EKS, VPC와 IAM을 다시 생성했고, 보존된 ECR을 import했습니다. ACK chart 1.15.1과 확장 컨트롤러를 실제 EKS에서 실행했습니다. 새 Runtime v1 생성, Gateway 연결과 Runtime v2 업데이트 후 모델 호출 및 PostSync AnalysisRun 성공을 확인했습니다.

같은 Gateway에서 단일 프로세스로 약 334초간 실행한 연속 요청은 180/180건 성공했습니다. 최대 동시 요청은 3개이고 짧은 JSON 요청입니다. 이 기록은 모든 부하의 무중단 보장이 아닙니다. 신규 세션은 v2로 전환됐고 기존 세션은 v1을 유지했습니다. 원격 Git을 바꾸지 않은 local values override 검증이므로 새 Git 커밋 Pull 기반 검증과 동일하지 않습니다.

별도의 2026-09-18 Git 변경 기반 시험에서는 106/106 응답을 확인했습니다. 두 시험은 버전과 배포 입력 방식이 다르므로 합산하지 않습니다.

## 공개용 사본 확인

이 폴더에 적용한 변경은 실제 계정 정보를 비운영 placeholder로 바꾸고 Argo CD의 chart 경로를 monorepo 구조에 맞추는 작업입니다. 로컬 테스트와 `cdk synth`, Helm 렌더링을 확인하더라도 새 사본을 별도 계정에 처음부터 배포했다는 의미는 아닙니다.

2026-09-22 확인한 결과:

| 대상 | 결과 |
|---|---|
| 원본과 monorepo 후보 Python 테스트 | 각각 58개 통과 |
| TypeScript 검사와 CDK 단위 테스트 | 통과, 테스트 3개 |
| 후보 CDK strict synth | 통과 |
| 기존 AWS 환경과 후보 CDK diff | ECR lifecycle의 `any`를 `untagged`로 바꾸는 의도한 차이 1건. 미배포 |
| 후보 Helm lint/template | 통과. Runtime, Gateway, GatewayTarget, ServiceAccount, AnalysisRun 렌더링 |
| 후보 ARM64 이미지 | 빌드 통과. UID 10001:10001, 네트워크를 차단한 로컬 `/ping` HTTP 200 |
| 기존 AWS 실제 호출 | Runtime version 2에서 `clean-v2`와 `clean-redeploy-v2` 모델 응답 확인 |
| 기존 Kubernetes 최신 상태 | 공인 IP 제한에 따른 timeout. 이번 점검에서 확인하지 못함 |

GitOps 경로 검사, 인증 파일 권한과 ECR 보존 정책의 보완은 로컬에만 반영했습니다. 이번 점검에서 CDK deploy, Helm upgrade, Git push와 공개 PR 생성은 하지 않았습니다. 후보 이미지도 로컬 빌드이며 기존 Runtime이 그 후보 이미지로 교체된 것은 아닙니다.

다음 검사를 반복할 수 있습니다.

```bash
npm ci
npm run check
npm test
uv run --directory agent pytest
helm lint charts/agentcore-agent -f docs/aws-tech-blog/snippets/dev-values.example.yaml
helm template devops-agent charts/agentcore-agent -n agentcore -f docs/aws-tech-blog/snippets/dev-values.example.yaml
```

CDK 합성에는 비운영 계정과 명시적 관리자 ARN/CIDR을 사용합니다. 실제 배포 전 `source scripts/environment.sh`, strict synth와 diff를 실행합니다. `cdk diff`에 차이가 없더라도 CloudFormation drift가 없다는 의미는 아닙니다.

공개 경로의 Git-only 재현은 자신이 관리하는 저장소에 소스를 커밋하고, placeholder와 계정별 values를 설정한 뒤 Argo CD가 해당 커밋을 가져오는 것까지 확인해야 합니다. 게시 승인 전에는 이 추가 단계를 생략한 채 “모든 코드의 완전한 재현을 확인했다”고 표현하지 않습니다.

새로운 빌드의 이미지 취약점 스캔, README의 처음부터 끝까지 재현, ACK 확장 패치의 라이선스 및 보안 검토는 [보안 안내](SECURITY.md)의 발행 조건을 따릅니다.

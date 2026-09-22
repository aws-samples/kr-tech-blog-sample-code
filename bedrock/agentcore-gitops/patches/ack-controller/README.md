# ACK HTTP Runtime target extension

공식 ACK `AgentRuntime` 지원을 사용하며 Gateway HTTP Runtime target과 named endpoint 업데이트 보정만 추가합니다. 기준 소스는 `aws-controllers-k8s/bedrockagentcorecontrol-controller`의 v1.15.1 commit `ba36b95fc5ec9ad1e8fa306fe339d227246bf601`입니다.

`build-ack-controller.sh`는 고정 commit을 다운로드하고 `endpoint-version.patch` 및 `extend_gateway.py`를 적용한 뒤 회귀 테스트와 ARM64 빌드를 수행합니다. 전체 upstream 소스나 실행 바이너리는 이 샘플에 포함하지 않습니다. 변경된 실행 파일을 넣은 이미지는 사용자의 ECR에 저장됩니다.

확장 범위는 `http.agentcoreRuntime.arn`과 `qualifier`, Gateway의 선택적 `protocolType`, SDK create/read/update 및 desired/observed 비교입니다. named endpoint는 관찰 버전 비교와 `EndpointName` 전달을 보정합니다. HTTP passthrough, inference target, HTTP schema/guardrail 전체를 지원하는 구현은 아닙니다. GatewayTarget 업데이트 매핑은 단위 테스트 범위이며 별도 live target 변경 시험은 수행하지 않았습니다.

서비스 CRD 네 개와 공통 ACK CRD 세 개를 먼저 적용하고 Helm에는 `--skip-crds`를 전달합니다. 이미지와 CRD는 함께 검증한 버전으로 유지하세요. patch 의존성을 숨기거나 stock ACK 전체 기능으로 소개하지 않습니다.

출처와 라이선스 검토:

- ACK upstream: `https://github.com/aws-controllers-k8s/bedrockagentcorecontrol-controller/tree/v1.15.1`, Apache-2.0.
- 기준 컨트롤러 이미지 및 Go 도구 이미지의 digest는 `Dockerfile`에 고정되어 있습니다.
- 빌드 시 다운로드하는 upstream 소스의 LICENSE와 NOTICE는 유지합니다. 상위 저장소의 라이선스가 외부 구성 요소의 라이선스를 대체하지는 않습니다. 빌드한 이미지를 재배포할 때에는 upstream 및 추가 의존성의 조건을 확인하세요.

원본 검증에서는 Go 테스트 18개와 패치 회귀 테스트 6개, 실제 Runtime/Gateway 호출 및 버전 전환을 확인했습니다. 공개 monorepo 커밋으로 새 Git-only 환경을 처음부터 배포하는 검증은 별도로 수행해야 합니다.

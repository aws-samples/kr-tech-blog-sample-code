# Amazon OpenSearch Service 두 도메인에서 비교하기

커스텀 Nori 빌드는 로컬에서 수행하고, 검색 엔진의 분석 결과는 Amazon OpenSearch Service에서 비교합니다. 로컬에 OpenSearch 서버를 설치하거나 실행하지 않습니다. 이 문서는 이미 생성된 도메인 두 개를 사용하며 클러스터 생성은 다루지 않습니다.

## 비교 구성

| 구분 | 도메인 A: 기본 Nori | 도메인 B: 커스텀 Nori |
| --- | --- | --- |
| 엔진 | OpenSearch 3.5 | OpenSearch 3.5 |
| 분석 플러그인 | AWS 제공 Nori | 로컬에서 빌드한 `analysis-nori-commerce` |
| tokenizer | `nori_tokenizer` | `nori_custom_tokenizer` |
| 등록 analyzer | `nori` | `nori_custom` |
| 인덱스 설정 | `samples/index-settings-stock.json` | `samples/index-settings-custom.json` |
| Dev Tools 요청 | `samples/analyze-stock.http` | `samples/analyze-custom.http` |
| 실습 인덱스 | `commerce-nori-stock-lab-v1` | `commerce-nori-custom-lab-v1` |

도메인 A에는 AWS 제공 Nori가 준비되어 있어야 합니다. 엔진 버전에 맞는 선택적 플러그인 연결 방법은 [지원 플러그인 문서](https://docs.aws.amazon.com/opensearch-service/latest/developerguide/supported-plugins.html)를 참고하세요. 도메인 B에 기본 Nori를 추가할 필요는 없으며, A에 커스텀 패키지를 연결하지 않습니다. 이미 다른 플러그인이 설치되어 있어도 이 실습을 위해 제거하지 않습니다.

두 도메인의 엔진 버전, 입력 문장, `decompound_mode`, 사용자 사전 규칙과 필터 구성을 맞춰 비교합니다. 클러스터별 `_score`나 응답 시간을 직접 비교하는 성능 실험은 아닙니다.

## 1. 로컬에서 커스텀 ZIP 빌드

[README](README.md)의 도구 준비를 마친 뒤 샘플 루트에서 실행합니다.

```bash
bash build-all.sh --install-deps
```

MeCab-Ko 엔진, 네이티브 사전, Lucene Nori 사전과 커스텀 플러그인이 순서대로 빌드됩니다. 배포할 파일은 다음과 같습니다.

```text
build/plugin/distributions/analysis-nori-commerce-1.0.0-os-3.5.0.zip
```

빌드 시의 네이티브 분석과 Java tokenizer 검사는 사전 검증입니다. OpenSearch 서버를 띄우지 않으며 AWS 자격 증명을 사용하지 않습니다. AWS에 배포하는 ZIP은 low 비용 사전 한 개입니다. high 비용 사전은 로컬 사전 검증용 비교군으로 남깁니다.

## 2. 기존 도메인과 권한 확인

AWS CLI 자격 증명, 두 도메인의 OpenSearch Dashboards 접근 권한, 실습 인덱스 생성 및 분석 권한을 준비합니다. VPC 도메인이면 해당 네트워크에 접근 가능한 환경에서 진행합니다. 기존 도메인의 보안 설정을 이 실습에 맞춰 완화하지 않습니다.

```bash
export AWS_REGION=ap-northeast-2
export STOCK_DOMAIN="your-stock-domain"
export CUSTOM_DOMAIN="your-custom-domain"

aws sts get-caller-identity

test "$STOCK_DOMAIN" != "$CUSTOM_DOMAIN"

for DOMAIN_NAME in "$STOCK_DOMAIN" "$CUSTOM_DOMAIN"; do
  aws opensearch describe-domain \
    --region "$AWS_REGION" --domain-name "$DOMAIN_NAME" \
    --query 'DomainStatus.{Name:DomainName,Engine:EngineVersion,Processing:Processing,Endpoint:Endpoint,Endpoints:Endpoints,EncryptionAtRest:EncryptionAtRestOptions.Enabled,NodeToNode:NodeToNodeEncryptionOptions.Enabled,HTTPS:DomainEndpointOptions.EnforceHTTPS,TLS:DomainEndpointOptions.TLSSecurityPolicy}'
done
```

도메인 이름이 서로 다르고 엔진이 모두 `OpenSearch_3.5`인지 확인합니다. 도메인 B는 저장 데이터 암호화, 노드 간 암호화, HTTPS 강제 적용과 `Policy-Min-TLS-1-2-PFS-2023-10` TLS 정책 등 [커스텀 플러그인 전제조건](https://docs.aws.amazon.com/opensearch-service/latest/developerguide/custom-plugins.html)을 충족해야 합니다.

아래 OpenSearch API 요청은 각 도메인의 **OpenSearch Dashboards > Dev Tools**에서 실행합니다. 도메인 A와 B를 서로 다른 브라우저 탭으로 열고 도메인 이름을 확인하세요. 명령행 HTTP 클라이언트로 대신 실행할 경우 각 엔드포인트에 맞는 인증된 HTTPS 요청을 사용합니다. 인증 없는 로컬 `curl` 명령을 서비스 엔드포인트로 바꿔 실행하지 않습니다.

## 3. 도메인 B에만 커스텀 패키지 연결

같은 계정과 리전의 기존 비공개 S3 버킷을 사용합니다. 매번 새 패키지 이름과 객체 키를 지정해 다른 실습의 산출물을 덮어쓰지 않습니다.

```bash
export BUCKET="your-private-artifact-bucket"
export RUN_ID="$(date -u +%Y%m%d%H%M%S)"
export PACKAGE_NAME="commerce-nori-os35-$RUN_ID"
export KEY="custom-nori-lab/$RUN_ID/analysis-nori-commerce-1.0.0-os-3.5.0.zip"
export ZIP="build/plugin/distributions/analysis-nori-commerce-1.0.0-os-3.5.0.zip"

aws s3 cp "$ZIP" "s3://$BUCKET/$KEY" \
  --region "$AWS_REGION" --sse AES256

export PACKAGE_ID="$(aws opensearch create-package \
  --region "$AWS_REGION" \
  --package-name "$PACKAGE_NAME" \
  --package-type ZIP-PLUGIN \
  --package-source "S3BucketName=$BUCKET,S3Key=$KEY" \
  --engine-version OpenSearch_3.5 \
  --query 'PackageDetails.PackageID' --output text)"

aws opensearch describe-packages \
  --region "$AWS_REGION" \
  --filters "[{\"Name\":\"PackageID\",\"Value\":[\"$PACKAGE_ID\"]}]" \
  --query 'PackageDetailsList[].{ID:PackageID,Status:PackageStatus,Error:ErrorDetails}'
```

`PACKAGE_ID`가 반환된 것만으로 검증이 끝난 것은 아닙니다. `AVAILABLE`을 확인한 뒤 다음 단계로 진행합니다. `VALIDATION_FAILED`라면 `ErrorDetails`를 확인하고 연결하지 않습니다. ZIP descriptor의 `opensearch.version=3.5.0`과 API의 `OpenSearch_3.5` 표기는 다릅니다.

도메인 B가 다른 구성 변경을 처리 중이면 완료될 때까지 기다립니다. `Processing=false`와 아래 변경 진행 상황을 함께 확인합니다. 변경 기록이 있다면 `COMPLETED`인지 확인한 뒤 연결합니다.

```bash
aws opensearch describe-domain-change-progress \
  --region "$AWS_REGION" --domain-name "$CUSTOM_DOMAIN"

aws opensearch associate-package \
  --region "$AWS_REGION" \
  --domain-name "$CUSTOM_DOMAIN" \
  --package-id "$PACKAGE_ID"

aws opensearch list-packages-for-domain \
  --region "$AWS_REGION" --domain-name "$CUSTOM_DOMAIN" \
  --query 'DomainPackageDetailsList[].{ID:PackageID,Status:DomainPackageStatus,Error:ErrorDetails}'
```

연결은 blue/green 배포로 진행됩니다. 해당 패키지가 `ACTIVE`이고 도메인 구성 변경이 완료된 뒤 분석 요청을 시작합니다. 도메인이 다른 변경을 처리 중이라는 오류가 나오면 새 도메인을 만들지 말고 현재 도메인의 변경 상태를 확인합니다.

각 도메인의 Dev Tools에서 다음 요청을 실행합니다.

```http
GET /

GET /_cat/plugins?v
```

A에는 AWS 제공 Nori가, B에는 `analysis-nori-commerce`가 있는지 각각 확인합니다. 기존 서비스 테스트에서 AWS Nori의 component 이름은 `opensearch-analysis-nori`였습니다. 모든 엔진과 패키지 버전에서 표시 이름이 같다고 가정하지 말고 실제 목록과 tokenizer 호출을 확인하세요.

## 4. 같은 입력을 각 도메인에서 분석

`samples/analyze-stock.http`는 A에서, `samples/analyze-custom.http`는 B에서 실행합니다. 두 파일의 요청 순서는 같으며 tokenizer와 등록 analyzer 이름만 각 플러그인에 맞게 다릅니다. 인덱스 경로를 사용하는 마지막 두 요청은 다음 절에서 인덱스를 만든 후 실행합니다.

예를 들어 비용 조정 결과는 tokenizer만 사용해 비교합니다.

도메인 A:

```http
POST /_analyze
{
  "tokenizer": {"type": "nori_tokenizer", "decompound_mode": "none"},
  "text": "노을빛무선청소기",
  "explain": true
}
```

도메인 B:

```http
POST /_analyze
{
  "tokenizer": {"type": "nori_custom_tokenizer", "decompound_mode": "none"},
  "text": "노을빛무선청소기",
  "explain": true
}
```

기존 AWS 테스트에서 기본 Nori는 `노을빛`, `무선`, `청소기`를, 커스텀 Nori는 `노을빛무선청소기`를 반환했습니다. 이는 기본 사전과 커스텀 사전의 비교입니다. 비용만 바꾼 high/low 비교는 로컬 네이티브 및 Java 사전 검증에서 수행했습니다.

`구름결캠핑의자`는 `none`, `discard`, `mixed`를 각각 맞춰 비교합니다. 커스텀 쪽은 원형 유지, `구름결 + 캠핑 + 의자`, 원형과 분해 토큰 동시 출력의 차이를 확인할 수 있습니다. `초록별접이식선반`에는 두 도메인 모두 같은 사용자 사전 규칙을 적용해 시스템 CSV 실험과 분리합니다.

응답의 토큰, offset, position, positionLength와 품사를 기록합니다. 기존 AWS 테스트에서는 기본 Nori가 일부 조사와 어미를 `J`, `E`로 표시했고, 로컬 빌드와 커스텀 플러그인은 `JKB`, `JKO`, `EC`, `EP` 등의 세부 품사를 반환했습니다. 이 차이를 토큰 경계 오류와 혼동하지 않습니다.

## 5. 도메인별 인덱스에 동일한 상품 색인

실습 인덱스 이름이 사용 중인지 먼저 확인합니다. 기존 인덱스가 있으면 덮어쓰거나 삭제하지 말고 새 이름을 정하고 이후 요청에도 반영합니다.

| 실행 위치 | 확인 요청 | 생성 요청 뒤에 붙일 JSON 본문 |
| --- | --- | --- |
| A | `HEAD /commerce-nori-stock-lab-v1` | `samples/index-settings-stock.json` |
| B | `HEAD /commerce-nori-custom-lab-v1` | `samples/index-settings-custom.json` |

인덱스가 없는 경우 각 Dev Tools에 `PUT /commerce-nori-stock-lab-v1` 또는 `PUT /commerce-nori-custom-lab-v1`을 입력하고, 바로 다음 줄에 해당 JSON 파일 **전체 내용**을 붙여 실행합니다. 파일 경로 자체를 요청 본문에 넣는 것이 아닙니다.

두 설정의 analyzer 이름과 매핑은 같습니다. A 설정에는 기본 Nori 구성요소만, B 설정에는 커스텀 Nori 구성요소만 들어 있습니다. 샤드 1개, 복제본 1개로 두었으므로 단일 데이터 노드 도메인에서는 복제본을 할당할 수 없습니다. 샤드와 복제본 수는 준비한 두 도메인에 맞춰 동일하게 조정하세요.

A의 Dev Tools:

```http
POST /commerce-nori-stock-lab-v1/_bulk?refresh=true
{"index":{"_id":"P001"}}
{"name":"노을빛무선청소기"}
{"index":{"_id":"P002"}}
{"name":"구름결캠핑의자"}
{"index":{"_id":"P003"}}
{"name":"별하늘진공텀블러"}
{"index":{"_id":"P004"}}
{"name":"초록별접이식선반"}

```

B의 Dev Tools에서는 경로를 `/commerce-nori-custom-lab-v1/_bulk?refresh=true`로 바꾸고 같은 본문을 실행합니다. Bulk 본문 끝에는 줄바꿈을 유지하며 응답의 `errors=false`와 각 항목의 성공 상태를 확인합니다. 이는 `samples/products.jsonl`의 상품 ID와 이름을 Bulk 형식으로 옮긴 것으로, 해당 파일을 그대로 `_bulk`에 보내는 형식은 아닙니다.

이제 두 요청 파일의 인덱스 `_analyze`와 `_search`를 실행합니다. 두 도메인에서 `캠핑 의자` 검색으로 `P002`를 찾는지 확인합니다. 이 검색은 색인과 검색 경로의 동작 확인이며, 커스텀 Nori에서만 검색되거나 검색 품질이 개선된다는 주장으로 해석하지 않습니다.

## 6. 실습 변경만 정리

실습에서 새로 만든 인덱스인지 확인한 뒤 각 도메인의 Dev Tools에서 삭제합니다.

```http
# A에서 실행
DELETE /commerce-nori-stock-lab-v1
```

```http
# B에서 실행
DELETE /commerce-nori-custom-lab-v1
```

이 실습에서 새로 등록한 패키지이고 다른 인덱스나 클라이언트가 사용하지 않을 때만 B의 연결을 해제합니다.

```bash
aws opensearch dissociate-package \
  --region "$AWS_REGION" --domain-name "$CUSTOM_DOMAIN" --package-id "$PACKAGE_ID"

aws opensearch list-domains-for-package \
  --region "$AWS_REGION" --package-id "$PACKAGE_ID"
```

연결 해제와 구성 변경 완료 후 사용 중인 도메인이 없음을 확인하고 패키지를 삭제합니다. 이어서 이번에 업로드한 정확한 S3 키만 삭제합니다.

```bash
aws opensearch delete-package --region "$AWS_REGION" --package-id "$PACKAGE_ID"
aws s3 rm "s3://$BUCKET/$KEY" --region "$AWS_REGION"
```

패키지 삭제 상태와 S3 객체 삭제 결과를 확인합니다. 버전 관리 버킷은 삭제 마커만 생성될 수 있으므로 이번에 업로드한 객체 버전도 버킷 운영 정책에 따라 정리합니다. 기존 도메인 두 개, AWS 제공 Nori, S3 버킷 자체와 기존 패키지는 삭제하지 않습니다.

## 검증 범위

2026년 9월 22일 AWS 임시 배포에서는 한 도메인에 기본/커스텀 Nori를 함께 연결해 분석 88건, 상품 색인 4건과 검색을 확인했습니다. 그 리소스는 모두 삭제했습니다. 상세 근거는 [AWS 배포 테스트 결과](AWS_DEPLOYMENT_TEST_RESULTS.md)에 있습니다.

이 문서는 같은 요청을 두 도메인으로 분리한 실습입니다. 분리한 요청과 인덱스 설정의 일관성은 오프라인 테스트로 확인하며, **두 도메인 구성으로 새로 배포해 전체 절차를 실행한 결과는 아직 아닙니다.** 두 도메인에서의 응답과 화면 캡처는 게시 검증 때 별도로 기록해야 합니다. 빌드 스크립트에 클러스터 생성, 배포 또는 자동 삭제 기능은 포함하지 않습니다.

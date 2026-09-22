# 명령어 실행 테스트 결과

이 문서는 아래에 명시한 이전 빌드 리비전의 실행 기록이다. 현재 실습은 [Amazon OpenSearch Service 두 도메인 비교](SERVICE_COMPARISON.md)로 변경했으며, 이력에 나오는 `make verify-http`와 로컬 서버용 검증기는 현재 코드에서 제거했다. 과거 결과를 보존하기 위해 실행 표에는 당시 명령을 그대로 남긴다.

## 두 도메인 실습으로 수정한 뒤의 검사

2026년 9월 22일 문서와 요청 파일을 분리한 뒤 다음 검사를 실제 실행했다. 새 AWS 배포나 로컬 OpenSearch 서버 실행은 하지 않았다.

| 검사 | 결과 |
| --- | --- |
| `make help` | 빌드 명령과 `SERVICE_COMPARISON.md` 안내 출력, 로컬 HTTP 진입점 제거 |
| `make test` | 기존 19개와 새 도메인별 샘플 검사 4개, 총 23개 통과 |
| `make verify` | tokenizer 108건, 격리 리소스와 ZIP 구조 검사 통과 |
| `bash -n scripts/build.sh` | 셸 문법 검사 통과 |
| 문서 코드 블록 검사 | Bash 문법, HTTP JSON과 Bulk 상품 데이터, 로컬 문서 링크 확인 |
| 문서 및 그림 원본 검사 | em dash와 중간점 제거, 공개 문서의 계정 정보 제외 확인 |

새 샘플 검사는 두 도메인의 인덱스 설정이 플러그인 구성요소 이름 외에는 같고, 각 요청이 자기 도메인의 tokenizer와 필터만 참조하며, 사용자 사전 규칙이 빌드 입력과 일치하는지 검사한다. 최종 ZIP의 SHA-256은 이전 AWS 검증 파일과 같았다. 두 도메인에서 전체 실습을 실행한 결과는 별도 확인 대상으로 남긴다.

## 실행 환경과 판정 기준

- macOS Apple Silicon, Python 3.12.12, Homebrew JDK 21.0.12.1.
- 부모 셸의 `JAVA_HOME`은 JDK 17.0.17을 가리킨 상태로 유지했다.
- 공개 저장소의 `2895f1a`를 새 디렉터리에 clone하고 이 변경의 JDK 선택 수정을 적용했다. 최초 실행 시 `sources/`, `.cache/`, `build/`는 없었다.
- 실행 기록의 UTC 시간은 2026-09-21 14:52:30부터 15:05:30까지다.
- 모의 빌드나 `make -n` 결과가 아니라 실제 프로세스의 종료 코드, 생성 파일과 분석 결과를 확인했다.
- 아래 시간은 이 개발 장비에서 한 번 실행한 관측값이다. 다운로드 속도와 캐시 상태가 달라지면 소요 시간도 달라진다.

## 발견한 오류와 수정

수정 전에는 JDK 17이 설정된 셸에서 `make setup`과 `make doctor`가 `Set JAVA_HOME to JDK 21.` 메시지와 종료 코드 2를 반환했다. 통합 스크립트와 달리 개별 단계는 설치된 JDK 21을 탐색하지 않았기 때문이다.

JDK 선택을 `scripts/bootstrap.sh`의 `select_java21()`로 통합하고 `scripts/env.sh`에서도 호출하도록 수정했다. 수정 후 두 명령은 같은 셸에서 종료 코드 0으로 통과했다. 잘못된 `NORI_JAVA_HOME`을 명시한 경우에는 대체 JDK를 선택하지 않고 실패하도록 유지했다. 부모 셸의 `JAVA_HOME`과 `javac 17.0.17`은 변하지 않았다.

## 실제 실행한 빌드 명령

모든 명령은 샘플 루트에서 실행하며 종료 코드 0을 확인했다. JDK 경로 자리표시자는 테스트 장비의 실제 JDK 21 경로로 대체했다.

| 명령 | 관측 시간 | 확인한 결과 |
| --- | ---: | --- |
| `bash build-all.sh --help` | 0.02초 | 옵션과 전체 빌드 범위 출력 |
| `make help` | 0.04초 | Make 진입점 출력 |
| `bash build-all.sh --install-deps` | 247.57초 | 빈 소스/캐시에서 다운로드, MeCab, 사전, Lucene, ZIP, 검증 완료 |
| `make fetch` | 0.57초 | 고정 커밋과 체크섬 재확인 |
| `make setup` | 1.02초 | 소스 준비와 JDK 21 검사 완료 |
| `make doctor` | 0.50초 | 도구 및 OpenSearch/Lucene 호환성 검사 |
| `make prepare` | 1.12초 | 기존 high/low 입력을 덮어쓰지 않고 확인 |
| `make mecab-engine` | 40.64초 | 새 엔진 소스 폴더에서 configure, make, install 수행 |
| `make mecab-dictionary` | 5.12초 | high/low 네이티브 사전 컴파일 |
| `make verify-mecab` | 1.29초 | 네이티브 실행 파일 해시와 실제 분석 8건 |
| `make lucene` | 28.42초 | Lucene 빌드와 high/low Nori 사전 변환 |
| `make plugin` | 6.55초 | ZIP 생성 및 동일 JVM에서 기본/커스텀 Nori 공존 |
| `make verify` | 2.99초 | tokenizer 108건, 리소스 격리와 ZIP 구조 |
| `make test` | 2.60초 | 오프라인 테스트 19개 |
| `bash build-all.sh --install-deps --mecab-only` | 50.67초 | 엔진과 사전 재빌드, native 분석 8건, 플러그인 단계는 실행하지 않음 |
| `make mecab` | 46.89초 | MeCab 단독 프로세스와 새 소스 빌드 기록 |
| `NORI_JAVA_HOME="/path/to/jdk-21" bash build-all.sh` | 78.39초 | 명시한 JDK로 전체 빌드 |
| `NORI_BUILD_DIR="$PWD/build/experiment-02" make all` | 80.13초 | 별도 출력 폴더에서 엔진부터 ZIP까지 생성 |
| `make all` | 78.07초 | 기본 Make 진입점으로 전체 빌드 |
| `bash build-all.sh` | 80.50초 | 기본 스크립트 진입점으로 전체 빌드 |
| `NORI_TEST_ENDPOINT=http://127.0.0.1:19235 make verify-http` | 2.61초 | 실행 중인 로컬 OpenSearch에 실제 분석 요청 88건 |

전체 빌드 5회 각각에서 `build-summary.json`의 `target=all`, `mecab_built_from_source=true`, `native_analysis_cases=8`, `nori_tokenizer_cases=108`과 실제 ZIP 파일을 확인했다. 엔진 소스 디렉터리가 실행마다 달라져 기존 실행 파일 때문에 엔진 빌드를 건너뛰지 않는 것도 확인했다. 캐시 재사용 실행도 MeCab은 새 소스 폴더에서 컴파일했다.

README의 MeCab 직접 호출 명령도 실행했다.

```bash
printf '노을빛무선청소기에서 먼지를 제거한다\n' | \
  build/toolchain/bin/mecab \
    -r build/toolchain/etc/mecabrc \
    -d build/native-low
```

출력 앞부분:

```text
노을빛무선청소기 NNP
에서 JKB
먼지 NNG
를 JKO
```

위 표시는 원래의 8개 feature 열 중 품사만 추린 것이다. 실제 출력에는 전체 feature와 마지막 `EOS`가 포함됐으며, 명령은 종료 코드 0으로 완료됐다. README의 configure/make/install 설명 블록은 단독 작업 폴더에서 복사 실행하는 용도가 아니라 `make mecab-engine` 내부에서 실제 수행되는 명령으로 검증했다.

## 오류 입력과 덮어쓰기 방지 검사

다음은 성공 종료가 아니라 의도한 실패를 확인하는 검사다.

| 입력 | 기대 종료 코드 | 결과 |
| --- | ---: | --- |
| `bash build-all.sh --unknown-option` | 2 | 알 수 없는 옵션 거부 |
| `NORI_JAVA_HOME=/nonexistent/jdk21 bash build-all.sh` | 1 | 잘못된 명시적 JDK 거부 |
| `NORI_BUILD_JOBS=0 bash build-all.sh` | 1 | 잘못된 병렬 수 거부 |
| `NORI_BUILD_DIR=relative-output bash build-all.sh` | 1 | 상대 출력 경로 거부 |
| `NORI_TEST_ENDPOINT=https://example.invalid make verify-http` | 2 | 외부 HTTP 검증 대상 거부 |
| 빈 출력 폴더에서 `make plugin` | 2 | Nori JAR가 없으면 패키징 중단 |
| 수정된 작업 사전을 대상으로 `make prepare` | 2 | 사용자 변경 보존, 자동 덮어쓰기 중단 |
| 같은 결과 폴더로 `make verify-http` 재실행 | 2 | 기존 HTTP 검증 결과 보존 |

정상 명령 27개와 의도한 실패 8개를 합쳐 35단계가 예상한 종료 코드로 완료됐다. 정상 명령 수에는 저장소 clone, 수정 적용, 런타임 압축 해제와 플러그인 설치 등 테스트 준비 단계도 포함한다.

## HTTP 검증과 정리

공식 OpenSearch 3.5.0 minimal Linux ARM64 압축 파일과 공식 Nori ZIP의 SHA-512를 확인하고, macOS의 외부 JDK 21로 루프백 서버를 실행했다. 이 절차는 Linux 네이티브 환경 검증이나 macOS 운영 지원을 주장하는 내용이 아니다.

기본 `analysis-nori`와 새로 빌드한 `analysis-nori-commerce`를 실제 설치했고 88개 분석 요청에서 token, POS, offset, position과 positionLength를 비교했다. 임시 인덱스는 검증기의 `finally`에서 삭제했다. 실행한 서버도 종료했으며 19235 포트가 더 이상 열려 있지 않음을 확인했다.

## 검증하지 않은 범위

- Homebrew 도구가 이미 설치된 환경이어서 `--install-deps`의 신규 패키지 설치 분기는 실행하지 않았다.
- 이 명령어 테스트에서는 Linux 환경의 MeCab 네이티브 빌드, AWS 패키지 등록과 도메인 연결을 수행하지 않았다. 이후 별도로 실행한 AWS 검증은 [AWS 배포 테스트 결과](AWS_DEPLOYMENT_TEST_RESULTS.md)에 기록했다.
- 사전 샘플의 토큰화 검증이며 대규모 검색 품질 또는 성능 평가가 아니다.
- 원문 로그, 절대 로컬 경로가 포함된 JSON과 빌드 산출물은 공개 소스에 포함하지 않는다.

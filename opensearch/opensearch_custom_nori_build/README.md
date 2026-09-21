# OpenSearch Custom Nori Build

MeCab-Ko 사전을 수정해 Lucene Nori JAR와 OpenSearch 커스텀 플러그인을 로컬에서 빌드하는 예제입니다. 기본 Nori와 함께 설치할 수 있도록 분석 이름, 한국어 분석 클래스, 사전 리소스를 분리합니다.

이 폴더에는 빌드 스크립트, 플러그인 소스, 가상 상품 사전과 검증 코드만 포함합니다. OpenSearch, Lucene, MeCab-Ko 원본 소스는 `make setup`이 공개 저장소에서 내려받습니다. Docker, AWS 자격 증명, Python 외부 패키지는 빌드에 필요하지 않습니다. AWS 리소스를 생성하거나 플러그인을 도메인에 배포하지 않습니다.

## 빠른 시작

macOS에서 Homebrew와 Xcode Command Line Tools를 준비합니다. 기존 `JAVA_HOME`이 JDK 17 등으로 설정되어 있으면 아래 명령으로 JDK 21을 명시해야 합니다. 스크립트는 사용자의 JDK 설정을 자동으로 바꾸지 않습니다.

```bash
git clone https://github.com/aws-samples/kr-tech-blog-sample-code.git
cd kr-tech-blog-sample-code/opensearch/opensearch_custom_nori_build

xcode-select -p
brew install openjdk@21 autoconf automake libtool python@3.12
export JAVA_HOME="$(brew --prefix openjdk@21)/libexec/openjdk.jdk/Contents/Home"
export PATH="$JAVA_HOME/bin:$PATH"

make all
```

최종 ZIP:

```text
build/plugin/distributions/analysis-nori-commerce-1.0.0-os-3.5.0.zip
```

Linux에서는 JDK 21, Python 3.12, Git, curl, tar, make, clang, autoconf, automake, GNU libtool을 준비하고 `JAVA_HOME`을 지정합니다. 실제 전체 빌드는 macOS Apple Silicon에서 검증했으며 Linux 빌드는 별도 확인이 필요합니다.

## 고정 버전과 외부 소스

| 구성요소 | 버전 | 사용 방식 |
| --- | --- | --- |
| OpenSearch | 3.5.0 | 소스의 Lucene 의존성 확인, 플러그인 API는 동일 버전 Maven artifact 참조 |
| Lucene | 10.3.2 | 공개 소스를 로컬 빌드하고 Nori 사전 변환에 사용 |
| MeCab-Ko | 0.996-ko-0.9.2 | 로컬 네이티브 도구 빌드 |
| mecab-ko-dic | 2.1.1-20180720 | 고정된 사전 원본에서 high/low 복사본 생성 |
| JDK | 21 | 컴파일과 검증 |
| Python | 3.12 | 표준 라이브러리만 사용 |
| Gradle | 8.14 | 다운로드한 Lucene 소스의 wrapper 사용 |

버전, Git 커밋 및 압축 파일 SHA-256은 `versions.env`에 있습니다. `scripts/fetch_sources.py`는 다음 공개 원본만 받아 `sources/`에 저장합니다.

- OpenSearch: `https://github.com/opensearch-project/OpenSearch.git`
- Lucene: `https://github.com/apache/lucene.git`
- MeCab-Ko: `https://bitbucket.org/eunjeon/mecab-ko/downloads/`
- mecab-ko-dic: Lucene testdata S3의 고정 아카이브

Git 소스는 태그로 shallow clone한 뒤 커밋을 확인합니다. 원격 주소, 커밋, 추적 파일의 변경이 예상과 다르면 중단합니다. 압축 파일은 SHA-256을 확인하고 Python의 안전한 tar 필터로 풉니다. 기존 소스에 `git reset`, `git clean`을 실행하거나 다른 버전으로 덮어쓰지 않습니다.

OpenSearch 서버 전체를 컴파일하지는 않습니다. 소스의 `gradle/libs.versions.toml`에 선언된 Lucene 버전과 이 샘플의 버전이 일치하는지 확인한 뒤, 독립 플러그인을 빌드합니다. OpenSearch 소스와 모든 Gradle wrapper 파일도 Git에 포함하지 않습니다.

## 빌드 단계

```bash
make setup
make prepare
make mecab
make lucene
make plugin
make verify
```

| 명령 | 입력 | 산출물 |
| --- | --- | --- |
| `make setup` | `versions.env` | `sources/`, `.cache/downloads/`, 도구 및 버전 확인 |
| `make prepare` | 원본 사전 아카이브, `dictionaries/*.csv` | `build/dictionary-high/`, `build/dictionary-low/` |
| `make mecab` | MeCab-Ko 엔진, 작업 사전 | `build/toolchain/`, `build/native-high/`, `build/native-low/` |
| `make lucene` | Lucene 소스, 작업 사전 | `build/nori-resources-*/`, `build/lucene-analysis-nori-*.jar` |
| `make plugin` | low 사전 JAR, `plugin/` | relocated JAR, 플러그인 ZIP |
| `make verify` | baseline/high/low JAR, 사용자 사전 | 분석 결과 JSONL, `build/verification.json`, ZIP SHA-256 |

`make all`은 다운로드부터 검증까지 실행합니다. 각 단계의 상세 로그는 `build/*.log`에 있습니다. 실패하면 해당 로그를 먼저 확인합니다.

MeCab 도구가 생성한 `sys.dic`와 `matrix.bin`은 네이티브 분석 검증용입니다. **Lucene DictionaryBuilder는 이 바이너리가 아니라 같은 CSV, `matrix.def`, `char.def`, `unk.def`를 읽습니다.** 생성된 `.dat`와 FST를 Nori JAR에 반영합니다. 플러그인 ZIP에는 MeCab 네이티브 실행 파일이나 라이브러리를 포함하지 않습니다.

## 예제 사전

| 상품명 | 비교 목적 |
| --- | --- |
| 노을빛무선청소기 | 단어 비용 변경에 따른 상품명 보존 |
| 구름결캠핑의자 | NNP/NNG 복합명사와 `none`, `discard`, `mixed` 비교 |
| 별하늘진공텀블러 | 추가 복합명사 사례 |
| 초록별접이식선반 | Nori 사용자 사전 분해 규칙 |

`dictionaries/high.csv`와 `dictionaries/low.csv`는 동일한 세 항목에 각각 `30000`, `-10000`의 단어 비용을 사용합니다. 비용 외의 열은 같습니다. 이 값은 효과를 보여주기 위한 실험값이며 검색 순위 boost나 운영 권장값이 아닙니다.

```csv
구름결캠핑의자,1786,3545,-10000,NNP,*,F,구름결캠핑의자,Compound,*,*,구름결/NNP/*+캠핑/NNG/*+의자/NNG/*
```

12열은 표면형, 왼쪽 문맥 ID, 오른쪽 문맥 ID, 단어 비용, 품사, 의미 분류, 종성, 읽기, 형태소 유형, 시작 품사, 끝 품사, 분해 표현입니다. 문맥 ID는 원본 사전과 품사/종성에 종속됩니다. 예제 준비기는 범위, ID 매핑, 중복 항목 및 복합명사 재구성을 검사합니다. 임의의 품사나 활용형까지 다루는 범용 CSV 편집기는 아닙니다.

`dictionaries/user_dictionary.txt`는 별도 형식입니다.

```text
초록별접이식선반 초록별 접이식 선반
```

Nori 사용자 사전에는 항목별 비용이나 임의 품사 열이 없습니다. 이 예제 버전에서는 NNG로 처리합니다. 비용 실험과 사용자 사전 실험을 분리해 같은 표면형의 우선순위가 섞이지 않게 합니다.

CSV를 수정한 후에는 새 출력 디렉터리를 사용합니다. 기존 작업 CSV가 달라졌으면 덮어쓰지 않고 중단합니다.

```bash
NORI_BUILD_DIR="$PWD/build/experiment-02" make all
```

기본 sample verifier는 제공된 상품명과 기대 결과를 검사합니다. 다른 용어로 교체할 때는 `tests/NoriCompare.java`와 해당 검증 기대값도 함께 수정해야 합니다.

## 플러그인 격리

플러그인 이름은 `analysis-nori-commerce`이며 다음 이름만 등록합니다.

```text
nori_custom
nori_custom_tokenizer
nori_custom_part_of_speech
nori_custom_readingform
nori_custom_number
```

Gradle Shadow가 `org.apache.lucene.analysis.ko`를 `example.opensearch.nori.internal.ko`로 이동하고 사전 리소스도 함께 옮깁니다. OpenSearch와 Lucene core/analysis-common은 compile-only 의존성으로 두고 ZIP에 중복 포함하지 않습니다. 기본 Nori의 SPI 서비스 파일도 제외합니다.

커스텀 tokenizer의 품사 정보에는 같은 커스텀 Nori 필터를 사용합니다. 기본 `nori_part_of_speech`와 임의로 섞지 않습니다. 등록 이름 하나만 바꾸거나 ZIP 파일명만 바꾸는 방식과 다릅니다.

## 검증

외부 네트워크나 AWS 호출 없이 준비 로직을 검증합니다.

```bash
make test
```

`make verify`는 9개 입력, 3개 분해 모드, baseline/high/low/user의 4개 조건으로 108건을 검사합니다. `make plugin`의 `verifyCoexistence`는 한 JVM에서 기본 Nori와 커스텀 Nori 사전을 함께 로드하고 다른 분석 결과가 나오는지 확인합니다.

샘플 결과:

```text
기본 Nori, none: 노을빛 + 무선 + 청소기
high 비용, none: 노을빛 + 무선 + 청소기
low 비용, none:  노을빛무선청소기

구름결캠핑의자, none:    구름결캠핑의자
구름결캠핑의자, discard: 구름결 + 캠핑 + 의자
구름결캠핑의자, mixed:   구름결캠핑의자 + 구름결 + 캠핑 + 의자
```

OpenSearch 프로세스를 별도로 준비해 공식 `analysis-nori`와 생성한 ZIP을 함께 설치했다면 HTTP 검증도 실행할 수 있습니다. 검증기는 인증 없는 요청이 외부로 나가지 않도록 loopback URL만 허용합니다.

```bash
NORI_TEST_ENDPOINT=http://127.0.0.1:19235 make verify-http
```

기존 서버의 버전과 플러그인 목록을 확인한 뒤 tokenizer/analyzer 요청 88건을 실행합니다. 고유한 이름의 임시 인덱스 하나를 만들고 `finally`에서 삭제합니다. `build/http-verification/`을 덮어쓰지 않으므로 재실행할 때는 이전 결과 폴더를 별도로 보존합니다. 서버 시작이나 플러그인 설치, AWS 도메인 배포는 자동 수행하지 않습니다.

수동 분석 요청은 `samples/analyze.http`, 인덱스 설정은 `samples/index-settings.json`을 참고하세요. 복제본 0은 로컬 실습용입니다. 토큰화 차이를 확인하는 샘플이며 검색 품질이나 서비스 배포 성공을 보장하지 않습니다.

### 확인한 범위

2026-09-21 macOS Apple Silicon, JDK 21, Python 3.12에서 이 폴더의 빈 `sources/`와 캐시로 공개 원본을 내려받아 전체 빌드를 확인했습니다. 준비 로직 테스트 10개, tokenizer 조합 108건, 같은 JVM의 사전 공존 검사, OpenSearch HTTP 분석 88건이 통과했습니다. HTTP 검증은 공식 OpenSearch 3.5.0 minimal Linux ARM64 배포판의 Java 구성을 외부 JDK 21로 실행한 루프백 테스트입니다. 테스트 인덱스와 프로세스는 정리했습니다. AWS 패키지 검증과 도메인 연결, Linux 네이티브 빌드는 수행하지 않았습니다.

## 환경 변수

| 변수 | 기본값 | 용도 |
| --- | --- | --- |
| `JAVA_HOME` | 기존 값, 미설정 시 Homebrew JDK 21 탐색 | JDK 21 경로 |
| `PYTHON_BIN` | `python3.12` | Python 3.12 실행 파일 |
| `NORI_BUILD_DIR` | 샘플 루트의 `build/` | 절대 출력 경로 |
| `NORI_BUILD_JOBS` | `4` | 빌드 병렬 수 |
| `GRADLE_USER_HOME` | 샘플 루트의 `.cache/gradle/` | Gradle 캐시 |
| `NORI_TEST_ENDPOINT` | `http://127.0.0.1:19235` | 선택적 로컬 HTTP 검증 |

## 공개 저장소에 포함하지 않는 파일

`.gitignore`가 `sources/`, `.cache/`, `build/`, `dist/`, `.gradle/`, Python 캐시, JAR/ZIP 및 압축 소스를 제외합니다. 업스트림 코드는 다운로드 스크립트로 재현하며 이 폴더의 소스로 복제하지 않습니다. 학습 노트북, 모델 가중치, 고객 데이터, AWS 계정 정보도 포함하지 않습니다.

## 라이선스

이 샘플 코드는 저장소의 MIT-0 라이선스를 따릅니다. 다운로드한 OpenSearch, Lucene 및 MeCab-Ko 소스와 사전은 각각의 라이선스를 따릅니다. 최종 ZIP에는 포함한 Lucene 및 사전의 LICENSE/NOTICE와 샘플 라이선스를 함께 넣습니다.

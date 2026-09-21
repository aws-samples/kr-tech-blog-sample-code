# OpenSearch Custom Nori Build

MeCab-Ko 사전을 수정해 Lucene Nori JAR와 OpenSearch 커스텀 플러그인을 로컬에서 빌드하는 예제입니다. 기본 Nori와 함께 설치할 수 있도록 분석 이름, 한국어 분석 클래스, 사전 리소스를 분리합니다.

`build-all.sh`는 도구 준비부터 **MeCab-Ko 엔진 소스 빌드, 네이티브 사전 컴파일, Nori 변환, 플러그인 ZIP 생성과 검증까지** 순서대로 실행합니다. MeCab이 미리 설치되어 있을 필요는 없습니다. OpenSearch, Lucene, MeCab-Ko 원본은 공개 저장소에서 내려받으며 이 폴더에는 빌드 코드와 샘플만 포함합니다. Docker나 AWS 자격 증명은 필요하지 않고 AWS 리소스도 변경하지 않습니다.

## 빠른 시작

macOS에서는 Homebrew와 Xcode Command Line Tools만 먼저 준비합니다. Command Line Tools가 없다면 `xcode-select --install`을 실행하고 설치를 완료합니다. 다음 명령은 누락된 JDK 21, Python 3.12, autoconf, automake, libtool을 Homebrew로 설치한 뒤 전체 빌드를 수행합니다.

```bash
git clone https://github.com/aws-samples/kr-tech-blog-sample-code.git
cd kr-tech-blog-sample-code/opensearch/opensearch_custom_nori_build

bash build-all.sh --install-deps
```

이미 도구를 준비했다면 `bash build-all.sh` 또는 `make all`로 실행할 수 있습니다. 통합 스크립트는 기존 `JAVA_HOME`이 JDK 17이어도 설치된 JDK 21을 찾아 **빌드 프로세스 안에서만** 사용합니다. 셸 설정 파일이나 전역 JDK 설정은 바꾸지 않습니다. 특정 JDK를 지정하려면 `NORI_JAVA_HOME`을 사용합니다.

```bash
NORI_JAVA_HOME="/path/to/jdk-21" bash build-all.sh
```

한 번의 실행으로 생성되는 주요 결과물:

```text
build/
├── toolchain/bin/mecab
├── toolchain/libexec/mecab/mecab-dict-index
├── toolchain/libexec/mecab/mecab-cost-train
├── toolchain/libexec/mecab/mecab-dict-gen
├── native-high/{sys.dic,unk.dic,matrix.bin,char.bin,dicrc}
├── native-low/{sys.dic,unk.dic,matrix.bin,char.bin,dicrc}
├── native-build.json
├── native-verification.json
├── lucene-analysis-nori-low.jar
├── plugin/distributions/analysis-nori-commerce-1.0.0-os-3.5.0.zip
└── build-summary.json
```

`build-summary.json`에서 `mecab_built_from_source`, 네이티브 도구 경로, 사전 경로, 분석 검증 건수와 최종 ZIP을 확인할 수 있습니다. 진행 중에는 단계 번호와 로그 경로를 출력하고, 실패하면 중단한 단계의 마지막 로그를 보여줍니다.

Linux에서는 JDK 21, Python 3.12, Git, curl, tar, make, clang, autoconf, automake, GNU libtool을 준비한 뒤 `bash build-all.sh`를 실행합니다. `--install-deps`는 macOS Homebrew 전용이며 시스템 패키지 관리자를 자동 실행하지 않습니다. Linux 전체 빌드는 별도 검증이 필요합니다.

## MeCab만 빌드하기

플러그인을 만들기 전에 MeCab-Ko 엔진과 사전만 확인하려면 다음 명령을 사용합니다. 필요한 공개 소스 다운로드, 엔진 빌드, high/low 사전 컴파일, 실제 분석 검증까지 수행하고 Lucene 컴파일 전에 종료합니다.

```bash
bash build-all.sh --install-deps --mecab-only
```

도구가 이미 준비되어 있으면 `make mecab`도 동일한 범위를 실행합니다. 별도 설치한 `/usr/local/bin/mecab`이나 Homebrew의 MeCab을 사용하지 않고, 이번에 컴파일한 `build/toolchain/bin/mecab`을 사용합니다.

```bash
printf '노을빛무선청소기에서 먼지를 제거한다\n' | \
  build/toolchain/bin/mecab \
    -r build/toolchain/etc/mecabrc \
    -d build/native-low
```

## MeCab 소스 빌드 과정

엔진 빌드 단계는 매번 새 `build/engine/build-*/` 디렉터리에 체크섬을 검증한 소스를 풉니다. 기존 실행 파일이 있어도 건너뛰지 않으며 다음 명령을 수행합니다. 이전 엔진 소스 작업 디렉터리는 보존합니다.

```bash
./configure --prefix="$NORI_BUILD_DIR/toolchain" \
  --with-charset=utf8 --enable-utf8-only \
  CC=clang CXX=clang++ CXXFLAGS='-O2 -std=c++11'
make -j4 CXXFLAGS='-O2 -std=c++11'
make install
```

이 코드는 빌드 과정 설명용이며 실제 경로와 병렬 수는 스크립트가 설정합니다. 설치 후 네이티브 도구 4개의 실행 권한과 해시, `mecab --version`을 확인합니다. `native-build.json`에는 사용한 소스 버전, 체크섬, configure/make/install 명령과 생성 도구 해시가 기록됩니다. 실패하면 미완료 표식을 남겨 이전 성공 결과를 새 빌드 결과로 사용하지 않도록 합니다.

사전 컴파일은 이번에 설치한 `mecab-dict-index`에 `dictionary-high/`와 `dictionary-low/`를 각각 전달합니다. `sys.dic`, `unk.dic`, `matrix.bin`, `char.bin`의 생성을 확인한 뒤 실제 MeCab 분석 8건으로 상품명 비용, 복합명사 정보, 조사 분리, 일반 문장 회귀를 검사합니다. `mecab-cost-train`과 `mecab-dict-gen`도 도구로 빌드하지만, CRF 학습을 실행하는 예제는 아닙니다.

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

권장 진입점은 `build-all.sh`입니다. 아래 개별 단계는 도구 환경과 소스가 준비된 상태에서 특정 단계만 다시 실행할 때 사용합니다.

```bash
make setup
make prepare
make mecab-engine
make mecab-dictionary
make verify-mecab
make lucene
make plugin
make verify
```

| 명령 | 입력 | 산출물 |
| --- | --- | --- |
| `make setup` | `versions.env` | `sources/`, `.cache/downloads/`, 도구 및 버전 확인 |
| `make prepare` | 원본 사전 아카이브, `dictionaries/*.csv` | `build/dictionary-high/`, `build/dictionary-low/` |
| `make mecab` | 공개 소스와 샘플 사전 | 다운로드부터 엔진/사전 빌드와 네이티브 검증까지 |
| `make mecab-engine` | MeCab-Ko 엔진 소스 아카이브 | `build/toolchain/`, `build/native-build.json` |
| `make mecab-dictionary` | 새로 빌드한 도구, 작업 사전 | `build/native-high/`, `build/native-low/` |
| `make verify-mecab` | 네이티브 도구와 컴파일된 사전 | `build/native-verification.json` |
| `make lucene` | Lucene 소스, 작업 사전 | `build/nori-resources-*/`, `build/lucene-analysis-nori-*.jar` |
| `make plugin` | low 사전 JAR, `plugin/` | relocated JAR, 플러그인 ZIP |
| `make verify` | baseline/high/low JAR, 사용자 사전 | 분석 결과 JSONL, `build/verification.json`, ZIP SHA-256 |

`make all`은 `build-all.sh`를 실행하므로 MeCab 엔진 빌드를 포함합니다. 같은 출력 디렉터리에서 여러 빌드를 동시에 실행하지 마세요. 로그는 `build/*.log`에 있으며 입력 CSV가 바뀌면 새 `NORI_BUILD_DIR`를 지정합니다.

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

외부 네트워크나 AWS 호출 없이 준비 로직, 통합 실행 순서, JDK 선택, MeCab 강제 소스 빌드와 실패 처리를 검증합니다.

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

2026-09-21 macOS Apple Silicon에서 소스, 캐시, 빌드 결과가 없는 독립 복사본으로 `bash build-all.sh --install-deps`를 실행했습니다. 셸 기본 JDK는 17이었지만 통합 스크립트가 설치된 JDK 21을 선택했습니다. Homebrew 의존성은 이미 설치되어 있어 추가 설치 없이 진행했습니다.

MeCab-Ko 소스의 configure/make/install, 네이티브 도구 4개 생성, high/low 바이너리 사전 생성, 실제 MeCab 분석 8건, Nori tokenizer 조합 108건, 같은 JVM의 사전 공존 검사와 최종 ZIP 생성을 확인했습니다. 이어서 `--mecab-only`를 같은 폴더에서 실행해 기존 엔진이 있어도 새 소스 디렉터리에서 다시 빌드되고 네이티브 분석 8건이 재통과하는지 확인했습니다. 오프라인 테스트 18개도 통과했습니다.

플러그인 코드의 이전 검증에서는 공식 OpenSearch 3.5.0 minimal Linux ARM64 배포판의 Java 구성을 외부 JDK 21로 실행한 루프백 환경에서 HTTP 분석 88건이 통과했습니다. 이번 빌드 절차 변경에서는 HTTP 테스트를 다시 실행하지 않았습니다. AWS 패키지 검증과 도메인 연결, Linux 네이티브 빌드는 수행하지 않았습니다.

## 환경 변수

| 변수 | 기본값 | 용도 |
| --- | --- | --- |
| `NORI_JAVA_HOME` | 미설정 | 통합 빌드에서 사용할 JDK 21 경로를 명시 |
| `JAVA_HOME` | 통합 빌드는 버전 확인 후 설치된 JDK 21 탐색 | 하위 빌드 프로세스의 JDK 경로 |
| `PYTHON_BIN` | `python3.12` | Python 3.12 실행 파일 |
| `NORI_BUILD_DIR` | 샘플 루트의 `build/` | 절대 출력 경로 |
| `NORI_BUILD_JOBS` | `4` | 빌드 병렬 수 |
| `GRADLE_USER_HOME` | 샘플 루트의 `.cache/gradle/` | Gradle 캐시 |
| `NORI_TEST_ENDPOINT` | `http://127.0.0.1:19235` | 선택적 로컬 HTTP 검증 |

## 공개 저장소에 포함하지 않는 파일

`.gitignore`가 `sources/`, `.cache/`, `build/`, `dist/`, `.gradle/`, Python 캐시, JAR/ZIP 및 압축 소스를 제외합니다. 업스트림 코드는 다운로드 스크립트로 재현하며 이 폴더의 소스로 복제하지 않습니다. 학습 노트북, 모델 가중치, 고객 데이터, AWS 계정 정보도 포함하지 않습니다.

## 라이선스

이 샘플 코드는 저장소의 MIT-0 라이선스를 따릅니다. 다운로드한 OpenSearch, Lucene 및 MeCab-Ko 소스와 사전은 각각의 라이선스를 따릅니다. 최종 ZIP에는 포함한 Lucene 및 사전의 LICENSE/NOTICE와 샘플 라이선스를 함께 넣습니다.

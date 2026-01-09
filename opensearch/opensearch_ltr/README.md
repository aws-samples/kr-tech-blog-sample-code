# Amazon OpenSearch Learning to Rank (LTR)

이 프로젝트는 Amazon OpenSearch Service에서 Learning to Rank(LTR) 기능을 테스트하기 위한 환경을 제공합니다.

## 개요

Learning to Rank(LTR)은 검색 결과의 순위를 매기는 기계 학습 기술입니다. 이 프로젝트에서는:

1. Amazon Bedrock의 Claude 3.5 모델을 사용하여 학습 및 평가 데이터 생성
2. RankLib을 사용한 랭킹 모델 학습
3. OpenSearch LTR 플러그인에 모델 배포 및 테스트

## 프로젝트 구성

- `ranklib_ltr_notebook.ipynb`: RankLib을 사용한 LTR 모델 학습 및 평가를 위한 주피터 노트북
- `data/`: 학습 및 평가에 사용되는 데이터 디렉토리
  - `documents.json`: 생성된 문서 컬렉션
  - `queries.json`: 생성된 검색 쿼리
  - `judgments.json`: 관련성 판단 데이터
  - `ranklib_train.txt`: RankLib 학습 데이터
- `models/`: 학습된 모델이 저장되는 디렉토리
  - `lambdamart_model.txt`: 학습된 LambdaMART 모델
- `lib/`: RankLib 라이브러리 디렉토리

## 주요 기능

1. **데이터 생성**: Amazon Bedrock의 Claude 3.5 모델을 사용하여 문서 컬렉션, 검색 쿼리, 관련성 판단(judgment) 데이터를 생성합니다.
2. **특성 추출**: 검색 결과 순위 학습에 필요한 특성(feature)을 추출합니다.
3. **RankLib 모델 학습**: 추출된 특성과 관련성 판단을 사용하여 RankLib 기반의 LambdaMART 모델을 학습합니다.
4. **OpenSearch 배포**: 학습된 모델을 OpenSearch LTR 플러그인에 배포하고 테스트합니다.
5. **성능 평가**: NDCG@5, NDCG@10 지표를 사용하여 모델 성능을 평가합니다.

## 특성(Feature) 정의

LTR 모델에 사용되는 특성은 다음과 같습니다:

1. **bm25_score**: BM25 알고리즘을 사용한 문서 관련성 점수
2. **title_match**: 제목 내 쿼리 단어 매칭 점수
3. **content_match**: 내용 내 쿼리 단어 매칭 점수
4. **title_length**: 제목 길이 (토큰 수)
5. **content_length**: 내용 길이 (토큰 수)

## 시작하기

1. 필요한 패키지 설치
```
pip install boto3 opensearch-py requests pandas numpy matplotlib py4j requests-aws4auth
```

2. 주피터 노트북 실행
```
jupyter notebook ranklib_ltr_notebook.ipynb
```

3. 노트북의 지시에 따라 데이터 생성, 모델 학습 및 평가 수행

## 요구사항

- Python 3.12
- Jupyter Notebook
- AWS 계정 (Amazon Bedrock 및 OpenSearch Service 접근 권한)
- Amazon OpenSearch Service 클러스터
- Java Runtime Environment JDK17(RankLib 실행용)
- 필요한 Python 패키지:
  - boto3
  - opensearch-py
  - requests
  - pandas
  - numpy
  - matplotlib
  - py4j
  - requests-aws4auth

## 참고 자료

- [Amazon OpenSearch Service 문서](https://docs.aws.amazon.com/opensearch-service/latest/developerguide/what-is.html)
- [OpenSearch Learning to Rank 플러그인](https://opensearch.org/docs/latest/search-plugins/search-relevance/ltr/)
- [RankLib 문서](https://sourceforge.net/p/lemur/wiki/RankLib/)
- [Amazon Bedrock 문서](https://docs.aws.amazon.com/bedrock/)

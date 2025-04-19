## Lambda layers for KR Blog
이 폴더는 Lambda 실행을 위한 레이어 파일을 제공합니다. 사용하는 환경(런타임, 아키텍처 등)에 따라 동작하지 않을 수 있으며 주로 샘플 코드 실행을 위한 경우가 대부분이므로 필요한 경우, 자체적인 [Lambda 레이어 구성](https://docs.aws.amazon.com/ko_kr/lambda/latest/dg/creating-deleting-layers.html)을 수행하시는 것을 권장드립니다.

## 📦 포함된 파일

1. `pyiceberg_layer.zip`: Python 3.13+, ARM64 기반으로 [PyIceberg](https://py.iceberg.apache.org/)를 사용할 수 있는 레이어입니다. (`pip install "pyiceberg[pyarrow]"`으로 설치됨)

## 🔧 사용 방법

1. **Lambda Layer 업로드**
   - 이 레포지토리에서 필요한 `.zip` 파일을 선택하여 Lambda Layer로 업로드합니다.
   - AWS Lambda 콘솔 또는 AWS CLI를 통해 Layer를 생성할 수 있습니다.

2. **Lambda 함수에 Layer 연결**
   - 해당 Layer를 사용하는 Lambda 함수의 설정에서 이 Layer를 추가하세요.

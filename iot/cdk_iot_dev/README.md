# AWS Cloud Development Kit(CDK)을 활용한 포티투닷(42dot)의 Fleet Management System(FMS) 자동화 사례

자동차 산업의 메가 트렌드 키워드인 CASE 는 연결(Connectivity), 자율주행(Autonomous), 공유(Sharing), 전동화(Electrification)로 정리할 수 있습니다.
그 중 커넥티비티는 IT 기술이 융합된 자동차가 세상과 연결되고 움직이는 생활공간으로 발전하며 다양한 모빌리티 서비스 제공이 가능하게 만드는 기반입니다.
그런데 모빌리티 서비스에서 연결된 차량이 급속도로 늘어나고 대상 지역이 글로벌로 확대됨에 따라 차량 관제 및 관리 시스템(FMS)도 차량 증가 속도와 지역별 다양한 컴플라이언스, 그리고 비즈니스 니즈에 빠르고 유연하게 대응할 수 있는 인프라가 필요합니다.
이 포스팅에서는 42dot 이 이러한 문제를 AWS IoT Core 와 AWS CDK 를 통해 해결한 과정을 소개합니다.

## 포티투닷(42dot) 소개
42dot 은 현대자동차그룹의 Global Software Center 로 service-defined 와 safety-designed 가치를 기반으로 소프트웨어가 중심이 되는 SDV (Software-defined Vehicle)를 통해 모든 것이 스스로 움직이고 연결된 세상에서 이동의 자유를 실현합니다.
42dot 은 자율주행 기술 구현 통합 솔루션 AKit 과 자율주행 모빌리티 통합 플랫폼 TAP!을 개발하고, 국내 최초 자율주행 유상운송 면허를 취득했습니다.
현재 서울 상암과 청계천에서는 누구나 TAP! 앱을 통해 42dot 의 자율주행차뿐만 아니라 다양한 기업의 자율주행차도 함께 호출할 수 있는 통합 자율주행 운송 서비스를 운영하고 있습니다.
차량 관제 및 관리 시스템(FMS)를 위해서는 차량 디바이스를 클라우드에 쉽고 안전하게 연결하고 대규모 디바이스 서비스 제공으로 검증된 AWS IoT를 활용하고 있습니다.
그리고 IaC(코드형 인프라, Infrastructure as Code)로 AWS CDK 를 사용하여 다양한 요구 조건에 맞는 IoT 인프라 구축을 자동화하고 있습니다.

## AWS IoT Core 소개
AWS IoT Core 는 IoT 디바이스들을 연결 및 관리하고, 다른 AWS 서비스들과 연동이 가능한 AWS 의 IoT 서비스입니다.
AWS IoT Core 는 [IoT Device SDK](https://docs.aws.amazon.com/iot/latest/developerguide/iot-sdks.html) 를 제공하며, 이를 기반으로 개발된 디바이스는 IoT Core 를 쉽게 사용할 수 있도록 해 줍니다.
IoT Core 는 디바이스와의 통신을 담당하며 'Core' 라는 단어처럼 AWS IoT 서비스에서 중심 역할을 합니다. IoT Core 는 메시지 라우팅을 통해 S3 같은 저장소, MSK 등과 같은 데이터 파이프라인과 함께 사용 될 수 있도록 합니다.
이와 더불어 AWS IoT 에서 함께 제공하는 [Greengrass](https://aws.amazon.com/greengrass/), [FleetWise](https://aws.amazon.com/iot-fleetwise/), [SiteWise](https://aws.amazon.com/iot-sitewise/)와 같은 서비스들을 활용하여 IoT 디바이스 운영 및 관리의 효율성을 높이는 방법도 있습니다.

## AWS CDK(Cloud Development Kit) 소개
[AWS Cloud Development Kit](https://aws.amazon.com/cdk/)(이하 AWS CDK)는 익숙한 프로그래밍 언어를 사용하여 클라우드 애플리케이션 리소스를 정의할 수 있는 오픈 소스 소프트웨어개발 프레임워크입니다.
이러한 코드를 통해 인프라를 관리하는 방식을 Infrastructure as a Code, 줄여서 IaC 라고 부릅니다. CDK 는 작성된 코드를 모두 [CloudFormation](https://aws.amazon.com/cloudformation/) 템플릿으로 변환하여 리소스들을 생성합니다. 비슷한 툴 중 가장 보편적으로 쓰이는 것은 테라폼(Terraform)입니다. 테라폼은 HCL(HashiCorp Configuration Language) 이라는 언어를 사용하여 다른 IaC 툴에 비해 진입 장벽이 조금 높습니다.
이에 반해 CDK 는 AWS 에서 제공하는 공식적인 IaC 툴이며 널리 쓰이는 다양한 언어로 IaC를 가능하게 한다는 장점이 있습니다.
AWS 에서 처음으로 IaC를 구현하고자 하는 분들 중 테라폼에 대한 사용경험이 없다면 AWS 가 제공하는 CDK 가 좋은 선택지가 될 것입니다.

<br/>

# 간단한 CDK 사용법

## 1. CDK 설치

설치 방법에 대해서는 [AWS CDK 설치하기](https://aws.amazon.com/ko/getting-started/guides/setup-cdk/)를 참조하시기 바랍니다. 터미널에서 npm 을 통해 CDK 를 설치합니다.

```shell
npm install -g aws-cdk
```

설치 후에는 다음의 명령어를 통해 설치 여부와 버전을 확인 가능합니다.

```shell
cdk --version
```

## 2. CDK 프로젝트 시작하기

CDK 코드를 작성할 빈 디렉터리를 하나 만들고, 터미널에서 다음 명령어를 통해 CDK 프로젝트를 시작합니다.
CDK 는 TypeScript(JavaScript), Python, Go, .NET 등 여러 가지 언어를 지원합니다.
본 포스팅에서는 TypeScript 를 이용해 CDK 코드를 구현해 보겠습니다.

```shell
mkdir cdk-test-project && cd cdk-test-project
cdk init --language typescript
```

Root directory 내에 초기화된 코드 트리가 생깁니다.

```shell
cdk-test-project
├── README.md
├── bin
│   └── cdk-test-project.ts
├── cdk.json
├── jest.config.js
├── lib
│   └── cdk-test-project-stack.ts
├── node_modules
├── package-lock.json
├── package.json
└── tsconfig.json
```

여기서 저희가 주로 작업해야 할 코드는 `/bin/cdk-test-project.ts`, `/lib/cdk-test-project-stack` 입니다.
CDK 는 `cdk init` 명령어를 통해 프로젝트가 초기화 되면, `/lib/cdk-test-project-stack.ts`라는 샘플 코드를 자동으로 생성합니다.
`stack` 은 리소스들의 모음을 뜻하는 오브젝트이며, `stack` 내부에 원하는 리소스들을 정의할 수 있습니다.
이렇게 정의된 stack 은 `/bin/cdk-test-project.ts` 에서 `app`으로 패키징 되어 배포가 가능하도록 구조가 구성되어 있습니다.
만일, stack 을 여러 개 정의할 경우, `/lib` 디렉터리 하위에 다른 stack 을 정의하고, stack 을 `/bin/cdk-test-project.ts` 코드에서 app 에 추가하면 됩니다.

## 3. CDK 프로젝트 AWS 와 연결하기

로컬에서 작업한 코드와 AWS 클라우드 환경을 연결하려면, `Bootstrap` 이라는 과정을 거쳐야 합니다.
AWS 계정 번호와 Region 정보를 넣어 다음의 명령어를 구성하고 실행합니다.

```shell
cdk bootstrap aws://ACCOUNT-NUMBER/REGION
```

## 4. CDK 프로젝트 배포하기

코드 작성이 끝나면 터미널 프로젝트 디렉터리에서 `cdk synth` 명령어를 통해 `AWS CloudFormation` 템플릿으로 구성해 볼 수 있습니다.
해당 명령어의 실행 결과는 root 디렉토리에 `cdk.out` 디렉토리가 생성되며 결과들이 저장됩니다.

```shell
cdk synth
```

`cdk diff` 명령어를 통해 기존에 배포된 내역과 현재 코드에 의해 정의된 리소스를 비교할 수 있습니다.

```shell
cdk diff
```

`cdk deploy` 명령어는 구성된 리소스 코드들을  AWS CloudFormation 에 배포하고, 순서대로 리소스들을 생성합니다.
이때, Stack 하나 혹은 전부를 배포할 수도 있습니다.

```shell
cdk deploy             # stack 이 하나인 경우
cdk deploy STACK_NAME  # 여러 개의 stack 중 특정 stack 하나만 배포할 경우
cdk deploy --all       # 여러 개의 stack 을 모두 배포할 경우
```

<br/>

# IoT 시스템 및 시나리오

## 1. IoT 시스템 아키텍처

![Sample system architecture](figures/system_architecture_msk.png)

본 포스팅을 위해서 간단한 IoT 시스템을 구성했습니다. 차량이 상태 관련 데이터를 클라우드로 보내고, 이 데이터를 MSK 클러스터로 전달하는 시스템입니다.
좀 더 기술적으로 시나리오를 기술해 보면 다음과 같습니다.

1. 차량에 장착된 디바이스는 MQTT 프로토콜을 이용해 IoT Core 로 차량 데이터를 송신합니다.
2. 메시지를 수신한 IoT Core 는 수신한 메시지를 Basic ingest 기능을 통해 MSK (Managed Streaming for Apache Kafka) 로 메시지를 전달합니다.

Basic ingest 는 AWS IoT Core 가 제공하는 Message Routing 기능 중 하나이며, 메시징 비용 없이 편리하게 다른 AWS 서비스로 메시지 전송을 가능하게 해줍니다.
구성하고자 하는 시스템에서 사용할 서비스는 크게 AWS IoT Core 와 MSK 두 가지입니다.
그러나 두 가지 서비스를 사용하기 위한 프로비저닝은 이보다는 조금 더 복잡합니다.

## 2. 디바이스 프로비저닝

### 2.1 시나리오에 따른 디바이스 프로비저닝

IoT 배포에서 보안은 디바이스 고객과 디바이스 제조업체 모두의 최우선 관심사입니다.
IoT 디바이스에서 AWS IoT Core 로 전송 중인 데이터를 보호하고 암호화하기 위해 AWS IoT Core 는 X.509 인증서를 사용하는 TLS 기반 상호 인증을 지원합니다.
디바이스 제조업체는 고유한 개인 키 및 X.509 인증서를 포함하여 고유한 ID를 각 장치에 프로비저닝해야 합니다.
또한 디바이스 제조업체는 각 디바이스에 대해 AWS 에 필요한 클라우드 리소스를 설정해야 합니다.

AWS IoT는 많은 수의 디바이스가 최종 고객에게 판매되기 전에 프로비저닝하고 온보딩할 수 있는 옵션을 제공하는데, 이는 디바이스 내에 고유한 X.509 인증서와 개인 키가 있는지 여부에 따라 달라집니다.
제조 체인에서 디바이스 제조업체가 제조 시 또는 배포 시 디바이스에 고유 자격 증명을 프로비저닝할 수 있는 경우, 디바이스 제조업체는 Just in Time Provisioning, Just in Time Registration, 또는 Multi-Account Registration 을 사용할 수 있습니다.
디바이스가 최종 고객에게 판매되기 전에 디바이스에 자격 증명을 제공할 수 없는 경우, 디바이스 제조업체는 Fleet Provisioning 을 사용하여 디바이스를 온보딩할 수 있습니다.
기술적 제약 또는 비용으로 인해 제조 시 디바이스에 고유 자격 증명을 프로비저닝하는 것이 어려운 경우가 많습니다. 제조업체에서 프로비저닝되지 않은 장치는 고유한 ID 없이 고객에게 판매됩니다. Fleet Provisioning 은 디바이스가 최종 고객에게 전달된 후 고유 자격 증명으로 디바이스를 프로비저닝하는 두 가지 방법(‘신뢰할 수 있는 사용자에 의한’ 또는 ‘클레임에 의한’)을 제공합니다.

이번 포스팅에서는 마지막 시나리오일 경우 제조 시 디바이스에 고유 자격 증명을 프로비저닝하는 것이 어려운 경우 사용하는 방법인 클레임에 의한 프로비저닝 방법을 사용합니다.
이는 사용자를 특정하기 어려운 B2C 상품에서 주로 사용하게 되는 방법입니다. 다시 말해, 수많은 불특정 다수가 사용할 디바이스이지만 관리 주체가 서비스 제공 업체일 경우 매우 유용하다는 장점이 있습니다.
이번 포스팅에서는 이에 더해 사전프로비저닝 훅 과 AWS Lambda 를 통해 디바이스를 검증하는 방법도 함께 구현해보겠습니다.

### 2.2 클레임에 의한 프로비저닝

[클레임에 의한 프로비저닝](https://docs.aws.amazon.com/ko_kr/iot/latest/developerguide/provision-wo-cert.html#claim-based)은 다음과 같은 과정을 거칩니다.

### 2.2.1 Before operation

1. 디바이스는 내부에 클레임 인증서(Claim Certificate, 이하 CC)를 저장하여 출고
2. 디바이스는 최초 사용 시 CC를 기반으로 AWS IoT Core 를 통해 접속
3. CC를 이용한 접속이 완료되면 IoT Core 는 최종적으로 사용할 영구 인증서(Permanent Certificate, 이하 PC)를 생성
4. IoT Core 는 최종적으로 PC 와 키를 전달하고, 디바이스는 이를 저장
5. 디바이스는 AWS IoT Thing 으로 등록 요청
6. AWS IoT는 사전 프로비저닝 훅으로 디바이스 검증용 Lambda 함수를 invoke
7. 디바이스 검증용 Lambda 함수는 단말의 유효성을 검증하기 위해 필요한 정보를 조회하여 IoT Core 의 프로비저닝 서비스에 조회 성공 여부 전달
8. 조회에 성공할 경우 프로비저닝 서비스는 프로비저닝 템플릿에 정의된 대로 클라우드 리소스를 생성
9. 디바이스는 클레임 인증서를 이용한 접속을 해제하고, 새 인증서로 AWS IoT Core 에 접속
10. Operation 시작

### 2.2.2 Operation

1. AWS IoT Thing 으로 등록된 디바이스는 AWS IoT Core 에 메시지를 전달
2. AWS IoT Core 는 수신한 메시지를 IoT Rule 을 통해 MSK 에 저장

위와 같은 절차를 순서도로 그려보면 다음과 같이 도식화할 수 있습니다.

![Sequence diagram](figures/sequence_diagram.png)

# 시스템 구축에 필요한 인프라 리소스

이제 시스템 구축에 필요한 인프라 리소스를 정의해 보겠습니다. 필요한 인프라 리소스 Stack 을 성격에 따라 크게 세 부분으로 나누었습니다.

## 프로비저닝 템플릿과 사전 프로비저닝 훅

- 구현 Stack 이름 : `AwsIotCoreProvisioningInfraStack`

첫 번째로 구현해야 할 것은 클레임 인증서를 가지고 있는 AWS IoT Thing 의 등록과 영구 인증서 발급, 이에 따르는 프로비저닝 서비스를 위한 템플릿 구현입니다.

## 클레임 인증서의 생성 및 저장

- 구현 Stack 이름: `AwsIotCoreProvisioningInfraStack`

두 번째로 구현해야 할 것은 클레임 인증서의 발급과 저장입니다.
이렇게 생성된 인증서는 디바이스 펌웨어에 함께 저장되어 출고되고, 최초 사용 시 영구 인증서 발급과 프로비저닝을 요청합니다.
클레임 인증서의 생성과 저장은 프로비저닝 템플릿에 의존하기 때문에 `AwsIotCoreProvisioningInfraStack` 안에서 같이 구현해 보겠습니다.

## IoT Rule 을 통한 메시지의 MSK 저장

- 구현 Stack 이름: `AwsIotCoreRuleInfraStack`

마지막으로는 운영에 들어간 디바이스에서 보고한 메시지의 전달과 저장입니다.
[AWS 개발자 안내서](https://docs.aws.amazon.com/ko_kr/iot/latest/developerguide/apache-kafka-rule-action.html)를 참조하여 Rule 을 구현합니다.
이 과정에서는 AWS IoT Core 의 `IoT Rule`을 사용하게 되며, `Basic ingest`을 통해 MSK 에 메시지들을 전달하게 됩니다.

<br/>

## 1. 코드와 함께 구현하기 

### 1.1 JSON 개발 패턴

필요한 모든 정책과 템플릿의 JSON 문서들은 AWS 공식 설명서의 [클레임에 의한 프로비저닝](https://docs.aws.amazon.com/ko_kr/iot/latest/developerguide/provision-wo-cert.html#claim-based) 파트를 기본으로 작성되었으며, 적절한 환경 변수를 코드 내에서 JSON 문서를 업데이트하는 방식으로 작업하겠습니다.
CDK 코드는 앞서 선언된 리소스의 property 들이 뒤쪽 리소스를 선언하는데 사용되는 경우가 잦은데, hard-coded JSON 문서를 사용할 경우 내용 변경 시 업데이트가 누락되는 경우가 있기 때문입니다.
JSON 문서의 업데이트 코드 때문에 초기 코드가 복잡해지나, JSON 문서를 업데이트 하는 패턴이 궁극적으로는 코드의 오류를 줄일 수 있습니다.

JSON 파일을 코드 내에서도 활용 할 수 있도록 [`tsconfig.json`](tsconfig.json) 에 다음의 설정을 추가해 줍니다.

```json
{
  "compilerOptions": {
    "moduleResolution": "node",
    "resolveJsonModule": true,
    "esModuleInterop": true
  }
}
```

### 1.2 Config 설정

[`config/config.ts`](config/config.ts) 에 필요한 설정을 추가합니다.
인증서를 생성하고 저장할 S3 버킷 의 이름을 지정합니다.
`s3BucketName` 은 목적에 따라 네이밍 하되, S3 정책에 따라 유일해야 합니다.
이번 포스팅에서는 `cdk-s3-test-bucket` 라는 이름을 사용하겠습니다.
 
이번 포스팅에서는 AWS IoT Core 의 인프라 리소스를 구성하는데 초점을 맞추어, MSK 리소스를 정의하는 내용은 생략하고 이미 생성되어있는 MSK cluster 를 사용하는 것으로 가정하겠습니다.
config.ts에 기 생성된 VPC 와 msk 와 관련한 대한 정보를 정의합니다. 

MSK 접속에는 credential (username, password) 도 필요하나, credential 은 Key Management Service(KMS) 와 secret manager 를 통해 stack 에서 정의되기 때문에 코드 내에서 생성하는 방식으로 사용하겠습니다.
메시지를 전달한 MSK topic 은 `test-msk-topic.rule1`, `test-msk-topic.rule2`, `test-msk-topic.rule3`를 사용할 예정입니다.
MSK topic 을 `config/config.ts` 내부에 정의하는 방식도 가능하지만 이번, 포스팅에서는 코드의 가독성을 위해 추후 정의할 `AwsIotCoreRuleInfraStack` 내에서 `test-msk-topic.${key}` 패턴으로 정의하도록 하겠습니다.

### 1.3 Initiation 된 Stack 과 App

`cdk init` 명령어를 통해 초기화된 디렉토리에서, 주로 다루게 될 코드는 다음의 두가지 파일입니다.

- [`cdkTestProjectApp`](bin/cdk-test-project.ts) - Stack 들을 묶어 cdk app 으로 만듭니다.

- [`AwsIotCoreProvisioningInfraStack`](lib/aws-iot-core-provisioning-infra-stack.ts) - App 에 필요한 stack 들을 구성합니다.

`cdk init` 명령어를 통해 초기화된 코드의 기본적인 Stack 이름은 `cdkTestProjectStack` 입니다.
이번 포스팅에서는 `AwsIotCoreProvisioningInfraStack` 를 구성한 뒤, 추가로 `AwsIotCoreRuleInfraStack` 을 생성하여 두 개의 stack 을 만들어 배포합니다.

먼저 기능적인 구별이 가능하도록 예제 stack 의 이름을 바꿔보겠습니다. 파일이름과 함께 `Stack id`(Stack 정의의 두번째 입력값) 도 함께 변경합니다.
이제 모든 준비가 완료되었고, 인프라 정의를 시작해보겠습니다. 

<br/>
 
## 2. 프로비저닝 템플릿과 사전 프로비저닝 훅

### 2.1 디바이스 정책

먼저, 프로비저닝이 마무리된 디바이스에 대한 정책 문서를 생성합니다.
정책 내용은 [기본 AWS IoT Core 정책 변수](https://docs.aws.amazon.com/ko_kr/iot/latest/developerguide/basic-policy-variables.html) 섹션을 기반으로 합니다.
[`device/device-policy.json`](lib/device/device-policy.json) 정책 문서를 `testDevicePolicyJson` 이라는 이름으로 `AwsIotCoreProvisioningInfraStack`에 삽입하고, 환경 변수에 맞게 업데이트 합니다.
그리고 수정된 문서를 기반으로 `aws_iot.CfnPolicy` construct 를 통해 AWS IoT 정책을 생성합니다.
이때, 주의할 것은 `{Action: ["iot:Publish", "iot:Receive", "iot:RetainPublish"]}` 에 해당하는 `Resource`와 `{Action: "iot:Subscribe"}` 에 해당하는 키워드가 `topic`과 `topicfilter`로 다르다는 점입니다.

### 2.2 사전 프로비저닝 Lambda 역할

사전 프로비저닝 훅에서 사용되는 Lambda 함수의 AWS IAM Role 을 적용합니다.
이 때, `iam.Role` 의 `assumedBy` 에는 Lambda 서비스를 사용합니다.

### 2.3 디바이스 확인을 위한 Lambda 함수

Lambda 함수의 리소스를 선언하기 전에, 사전 프로비저닝 훅을 통해 실행되는 디바이스의 시리얼 정보를 검증용 Lambda 함수를 생성합니다.
간단한 검증을 수행하는 파이썬 코드를 [`lib/device/verify-devices-lambda`](/lib/device/verify-devices-lambda.py) 와 같이 구성하였습니다.
문제를 간단하게 만들기 위해 데이터베이스나 파일을 조회하는 대신 `SerialNumber`가 `297468`로 시작하는지 검증하고, 검증 결과에 따라 `True` 혹은 `False` 값을 반환하도록 구성합니다.

Lambda 함수를 `verifyDevicesLambda` 라는 이름으로 `AwsIotCoreProvisioningInfraStack`에 삽입하고, 환경 변수에 맞게 업데이트 합니다.
다음으로는 사전 프로비저닝 훅을 선언하고, `addPermission` 메소드를 통해 AWS IoT Service principle 이 해당 Lambda 함수를 호출 할 수 있도록 허용합니다.

Lambda 함수의 리소스를 선언할 때는 code 경로와 handler 경로에 유의합니다. Lambda code 는 `lambda.Code.fromAsset` 메서드를 통해 파일로 구성된 코드를 그대로 들고 올 수 있습니다.
handler 는 Lambda 내에서 `handler: "{python 파일 이름}.{실제 동작하는 함수의 이름}"` 과 같이 작성합니다.
마지막으로 AWS IoT 서비스가 해당 Lambda 함수를 invoke 할 수 있도록 허용합니다.

### 2.4 프로비저닝 템플릿을 위한 역할

프로비저닝 서비스에 대한 역할(Role)을 생성합니다. 프로비저닝 서비스는 실제로 IoT 서비스에서 동작하므로, `assumedBy`는 `"iot.amazonaws.com"`로 설정합니다.

### 2.5 프로비저닝 템플릿

프로비저닝 템플릿의 베이스 문서는 AWS 공식 개발자 안내서의 [플릿 프로비저닝 템플릿 예](https://docs.aws.amazon.com/ko_kr/iot/latest/developerguide/provision-template.html#bulk-template-example:~:text=%EC%9E%91%EC%84%B1%ED%95%A0%20%EC%88%98%20%EC%9E%88%EC%8A%B5%EB%8B%88%EB%8B%A4.-,%ED%94%8C%EB%A6%BF%20%ED%94%84%EB%A1%9C%EB%B9%84%EC%A0%80%EB%8B%9D%20%ED%85%9C%ED%94%8C%EB%A6%BF%20%EC%98%88,-%7B%0A%20%20%20%20%22Parameters%22)에서 확인할 수 있습니다.
레퍼런스를 참조하여 프로비저닝 템플릿을  [lib/device/provisioning-template.json](lib/device/provisioning-template.json)에 작성합니다.
이번 포스팅에서는 플릿 프로비저닝 시에 사용할 `ThingName` 패턴을 `test-thing-{SerialNumber}`로 지정하고, 기본 템플릿의 `Resources.thing.Properties.ThingName.Fn::Join`에 정의한 패턴과 일치하도록 선언해줍니다. 

`AWSIotCoreProvisioningInfraStack`에서 앞서 구성된 템플릿에 프로비저닝 서비스에 대한 정책을 연결하고, `CfnProvisioningTemplate` construct 를 통해 프로비저닝 템플릿 리소스로 변환합니다.

사전 프로비저닝 훅은 `CfnProvisioningTemplate` construct 내부의 `preProvisioningHook` 파라미터를 통해 설정합니다.
`preProvisioningHook` 옵션에는 간단히 `payloadVersion` 과 위에서 정의한 Lambda 의 `targetArn`을 파라미터로 설정합니다.

 <br/>

## 3. 클레임 인증서와 관련된 리소스

### 3.1 CDK 를 통해 구현되지 않는 리소스

AWS IoT Core 의 경우 일반적으로 콘솔을 이용하여 인프라를 구축합니다. 리소스 요소가 많고, 서로 얽혀 있어 콘솔을 통해 직관적으로 구현하는 것이 가장 편하기 때문입니다.
매뉴얼상의 콘솔 명령어와 CDK construct 가 1:1로 매칭되지 않거나 콘솔 명령어가 CDK construct 조합으로 구성되지 않을 경우에는 아래 리소스를 참고할 수 있습니다.

- [ConstructHub](https://constructs.dev/)
    - AWS 에서 운영하는 IaC를 위한 Hub 로, AWS CDK 뿐만 아니라 Terraform 등 다양한 도구들의 construct 들을 찾을 수 있습니다.
- [AWS custom resources](https://docs.aws.amazon.com/cdk/api/v2/docs/aws-cdk-lib.custom_resources.AwsCustomResource.html)
    - CDK 에서 지원하는 custom 리소스
    - 명령어가 좀 더 풍부한 SDK API 를 활용하여 원하는 리소스를 생성 가능합니다.

이번 섹션에서는 CDK 로 구현이 되지 않는 AWS IoT 인증서 생성에 대해서 AWS Custom resource 를 활용해 보도록 하겠습니다.

### 3.2 S3 버킷 생성

클레임 인증서를 저장할 AWS S3 버킷을 `AWSIoTCoreProvisioningInfraStack`에 선언합니다.
[`config/config.ts`](config/config.ts) 에서 정의한 `S3bucektName`변수를 S3 버킷의 이름으로 사용합니다.
기존에 사용하던 버킷을 그대로 사용하려면 버킷 클래스의 다른 method([fromBucketArn](https://docs.aws.amazon.com/cdk/api/v1/docs/@aws-cdk_aws-s3.Bucket.html#static-fromwbrbucketwbrarnscope-id-bucketarn), [fromBucketAttributes](https://docs.aws.amazon.com/cdk/api/v1/docs/@aws-cdk_aws-s3.Bucket.html#static-fromwbrbucketwbrattributesscope-id-attrs), [fromBucketName](https://docs.aws.amazon.com/cdk/api/v1/docs/@aws-cdk_aws-s3.Bucket.html#static-fromwbrbucketwbrnamescope-id-bucketname))들을 활용하시면 됩니다.

### 3.3 클레임 인증서 정책

[`device/cc-policy.json`](lib/device/device-cc-policy.json)에서 클레임 인증서에 대한 정책을 정의합니다.
클레임 인증서에 대한 정책도 기본적인 IoT 정책을 기반으로 합니다. 클레임 인증서에 대한 정책 정의는 AWS 개발자 안내서의 [클레임에 의한 프로비저닝](https://docs.aws.amazon.com/ko_kr/iot/latest/developerguide/provision-wo-cert.html#provision-mqtt-api:~:text=%EC%82%AC%EC%9A%A9%EC%9E%90%EC%97%90%20%EC%9D%98%ED%95%9C%20%ED%94%84%EB%A1%9C%EB%B9%84%EC%A0%80%EB%8B%9D-,%ED%81%B4%EB%A0%88%EC%9E%84%EC%97%90%20%EC%9D%98%ED%95%9C%20%ED%94%84%EB%A1%9C%EB%B9%84%EC%A0%80%EB%8B%9D,-%EB%94%94%EB%B0%94%EC%9D%B4%EC%8A%A4%EB%8A%94%20%ED%94%84%EB%A1%9C%EB%B9%84%EC%A0%80%EB%8B%9D%20%ED%81%B4%EB%A0%88%EC%9E%84) 을 참고하시면 됩니다.

위에서 정의된 베이스 정책 문서에 필요한 내용을 업데이트하고, `AWSIotProvisioningInfraStack` 내부에 `CfnPolicy` stack 을 통해 `testDeviceClaimCertificatePolicy`라는 이름의 정책을 생성합니다.
클레임 인증서를 통해 프로비저닝을 요청하기 때문에, `provision`과 같은 정책 정의가 필요합니다.

### 3.4 클레임 인증서 (CustomResource 사용)

AWS IoT Core 콘솔에서는 `보안 - 인증서` 탭을 통해 쉽게 인증서를 만들 수 있으나, CDK 에는 콘솔 명령어와 매칭되는 construct 가 없습니다.
인증서는 [Open SSL](https://www.openssl.org/docs/) 등을 활용하여 생성하는 방법도 가능하나, IaC를 위한 통합이 어려운 점이 있습니다.

앞서 말씀드린 것처럼 `AwsCustomResource`를 활용하여 인증서를 생성하고, 이를 S3에 저장해 보도록 하겠습니다.
AWS SDK 의 [`CreateKeysAndCertificate` API](https://docs.aws.amazon.com/iot/latest/apireference/API_CreateKeysAndCertificate.html) 를 활용합니다.
`CreateKeysAndCertificate` 를 호출함으로써 `outputPath` 에 정의되어 있는 네 가지 object  `"certificateArn"`, `"certificatePem"`, `"keyPair.PublicKey"`, `"keyPair.PrivateKey"` 를 얻게 됩니다.

### 3.5 S3 에 키 배포 (CustomResource 사용)

위 과정에서 얻은 클레임 인증서 object 들을 위에서 만든 S3 버킷에 저장합니다.
CDK 상에서 버킷 리소스를 `cdkTestS3Bucket` 로 정의하였고, 이를 `destinationBucket` 의 `claim-certificate` key 에 저장하도록 합니다.

### 3.6 클레임 인증서를 위한 정책 연결

마지막으로, 생성한 클레임 인증서와 클레임 인증서 정책을 연결시켜 줍니다.

<br/>  

## 4. IoT Rule 을 통한 메시지의 MSK 전달

Rule engine 을 통한 메시지의 MSK 전달을 위해 새로운 스택을 만듭니다.
`lib/aws-iot-core-rule-infra-stack.ts`파일을 추가하고, 여기에 `AwsIotCoreRuleInfraStack`라는 이름의 Stack 을 추가합니다.
여기서는 rule engine 의 정책을 정의하기 위한 [`lib/rule/rule-policy.json`](lib/rule/rule-policy.json)과 규칙기반 필터링을 위한 [`lib/rule/rule-keys.json`](lib/rule/rule-keys.json) 그리고 키 정책을 위한 [`lib/rule/key-policy.json`](`lib/rule/key-policy.json`) 문서를 사용할 예정입니다.

### 4.1 Rule Engine 을 위한 역할

AWS IoT Core 내부 서비스 중 하나로 Rule engine 이 있습니다. Rule engine 은 다른 서비스로의 메시지 전달이 가능하도록 다양한 Rule 을 제공합니다.
Rule engine 이 동작하기 위한 AWS IAM Role 을 만듭니다.
IoT Core 에서 사용할 역할로, `assumedBy` 에 `iot.amazonaws.com` 을 지정합니다.


### 4.2 Rule Engine 를 위한 정책

Rule engine 에 필요한 역할의 정책을 정의합니다.
MSK 로 메시지를 전달하기 위해 `ec2`, `AWS Secrets Manager` 와 `AWS key management Service(kms)` 의 다양한 권한이 필요합니다.
EC2에 접근하기 위한 권한들과, 키의 암호화 관련 권한들입니다. 자세한 권한의 내용은 [`lib/rule/rule-policy.json`](lib/rule/rule-policy.json) 내부에 기술 되어 있습니다.
정책을 만든 뒤에는 앞서 만든 IAM 역할에 할당합니다.

### 4.3 MSK 를 위한 TopicRuleDestination

MSK 클러스터에 맞는 보안그룹과 VPC 를 설정해주고, `ruleEnginePolicy` 의존성을 추가합니다.
의존성은 `CfnTopicRuleDestination` 작업 이전에 `ruleEnginePolicy` 가 먼저 정의되어야 함을 의미합니다.

### 4.4 IoT Core 에서 MSK 에 접근하기 위한 키

[`lib/rule/key-policy.json`](lib/rule/key-policy.json)으로부터 정의된 keyPolicy 문서에 계정을 업데이트 하고, AWS Key Management(KMS) 를 사용하여 IoT Core 에서 MSK 에 접근하기 위해 필요한 키를 생성합니다.
`kms.CfnKey` 를 통해 kms 키를 생성하고, `kms.CfnAlias` 를 통해 키에 별칭을 부여합니다.
[개발자 안내서](https://docs.aws.amazon.com/kms/latest/developerguide/kms-alias.html)에 따르면 별칭을 부여하는 것이 키 인식과 관리에 유리하다는 점을 안내하고 있습니다.  
마지막으로 `secretemanager.CfnSecret`를 통해 IoT Core 에서  MSK 접속을 위한 Secret Manager 비밀번호를 생성합니다.

### 4.5 pre-defined key 를 위한 Rule

마지막으로 Rule 을 작성합니다. 본 포스팅에서는 `rule1`, `rule2`, `rule3` 세 가지의 Rule 을 작성하도록 합니다.
Rule 의 생성에는 [`lib/rule/rule-keys.json`](lib/rule/rule-keys.json)를 활용합니다.
Rule 생성 시에는 for loop 를 활용하여 JSON 문서를 읽고, 여러개의 rule 을 간단하게 생성하도록 구현합니다.

`CfnTopicRule` 의 생성자에는 `ruleName` 과 `topicRulePayload` 라는 두 가지 필수 인자가 있습니다.
`ruleName` 에 적절한 이름을 지정합니다. 다만, AWS IoT 의 규칙에 따라 '-(dash)'는 `ruleName` 에 사용할 수 없습니다.

`topicRulePayload` 에는 rule 의 내용을 정의합니다.
`sql` 에서 사용할 필터링 구문은 [`AWS IoT SQL`](https://docs.aws.amazon.com/iot/latest/developerguide/iot-sql-reference.html)을 참고하여 작성하고,
`actions` 에는 rule 을 만족했을 때 MSK 로 전달하기 위해 필요한 MSK 접속정보, topic 이름, `destinationArn` 을 정의합니다.
JSON 문서에 정의된 key 들을 활용하여  MSK 내에 생성된 topic 이름을 `test-msk-topic.key` 라고 가정하고, rule 을 생성합니다.

이제 모든 과정이 완성되었습니다. IoT Device 에서 보내는 메시지를 `test-rule/${key}` 토픽에 맞추어 메시지를 전송하면,
AWS IoT 는 바로 MSK 의 `<test-msk-topic>.${key}` 로 메시지를 전송합니다.
이와 같이 간단한 Rule 정의를 통해 다른 AWS 서비스로 메시지를 전달하는 기능을 `Basic ingest` 라고 합니다.
Basic ingest 를 활용하면 과금되지 않으며, 다른 AWS 서비스로 메시지를 전달하는데 필요한 비용은 발생하지 않는다는 장점이 있습니다.

<br/>

## 5. 작업을 통해 구현된 CDK App 의 구조

cdk init 후에 작성된 파일들을 트리구조로 나타내보면 다음과 같습니다.

```shell
cdk-test-project
├── README.md
├── bin
│   └── aws-iot-infra.ts
├── cdk.json
├── config
│   └── config.ts
├── jest.config.js
├── lib
│    ├── aws-iot-core-provisioning-infra-stack.ts
│    ├── aws-iot-core-rule-infra-stack.ts
│    └── device
│    │    ├── device/device-cc-policy.json
│    │    ├── device/device-policy.json
│    │    ├── device/provisioning-template.json
│    │    └── device/verify-devices-lambda.py
│    └── rule
│         ├── rule/key-policy.json
│         ├── rule/rule-keys.json
│         └── rule/rule-policy.json
├── node_modules
├── package-lock.json
├── package.json
└── tsconfig.json
```

<br/>

# 결론

이번 포스팅에서는 AWS IoT Core 를 기반으로 한 디바이스 데이터 수집 시스템을 구상하고, 다음과 같은 시나리오와 리소스를 구성해 보았습니다.
구성한 시나리오와 리소스를 요약하자면 다음과 같습니다.

## 운영 시나리오
1. Device 에서 생성된 메시지를 AWS IoT Core 로 전달
2. 클레임에 의한 인증서 발급 방법으로 인증서를 발급하여 사용
3. 디바이스 검증을 위해 사전 프로비저닝 훅을 사용 CDK 를 통해 IoT Core 를 기반으로 한 서비스의 IaC를 구현하고 디바이스를 이용해 검증
4. IoT Core 는 Rule engine 의 Basic ingest 기능을 활용하여 MSK 로 메시지 전달 

## AWS CDK 를 통해 생성한 리소스들

### 프로비저닝 템플릿과 사전 프로비저닝 훅 구현
디바이스 정책, 디바이스 검증용 Lambda 프로비저닝 서비스의 IAM 역할, 프로비저닝 템플릿 등 정의

### 클레임 인증서의 생성 및 저장 
S3 버킷 정의, 클레임 인증서에 대한 정책, AwsCustomResource 를 활용한 클레임 인증서 발급, 발급된 인증서의 저장, 인증서와 정책 연결

### 디바이스가 전달한 메시지를 AWS IoT Core Rule Engine 의 Basic ingestion 을 통해 MSK 로 전달
Rule engine 역할, Rule engine 역할 정책 및 역할 연결, MSK 로 메세징 Rule 정의

이번 포스팅에서는 AWS IoT Core 를 이용하여 디바이스 등록부터 데이터 저장까지 가능한 인프라를 AWS CDK 를 이용해 구성해 보았습니다.
처음 서비스를 위한 인프라를 구축하려할 때, EC2나 S3 등 개별 서비스 리소스의 기능들을 이해하고 나서, 리소스 생성과 관리작업으로 넘어가게 됩니다.
이때 CDK 는 AWS 가 제공하는 툴로써 가장 높은 호환성을 보장하며, AWS 서비스 기반 아키텍처를 IaC로 구축하는데 기초적인 도구가 될 수 있습니다.
IoT 서비스는 장비 운영자와 서비스 개발자가 눈으로 확인된 동작에 기반해 결정 및 변경 되어야 할 사항이 많기 때문에 클라우드 인프라에서 미리 준비해 두어야할 구성요소가 많고 변경이력에 대해 민감한 편입니다. 
이를 콘솔에서 편리하게 생성하는 것도 가능은 하겠으나, 코드를 기반으로 관리하면 지역이나 국가별 요건을 맞게 수정하는 것이 용이하고 필요한 인프라를 빠르게 배포할 수 있고 수작업에 따른 휴먼 에러도 줄일 수 있습니다.
이 부분은 SDK 의 기능을 CDK 에서 활용할수 있게 지원해주는 AwsCustomResource 기능을 활용하여 이를 해결할 수 있습니다.
이상으로 포스팅을 마칩니다. 이 포스팅을 통해 AWS IoT 개발자 여러분들게 도움이 되기를 바랍니다.

감사합니다.


## References

[AWS CDK Documentation](https://docs.aws.amazon.com/cdk/v2/guide/home.html)

[AWS CDK API reference](https://docs.aws.amazon.com/cdk/api/v2/docs/aws-construct-library.html)

[AWS CDK Examples GitHub](https://github.com/aws-samples/aws-cdk-examples)

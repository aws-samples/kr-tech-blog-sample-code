# AWS Tech Blog Korea - Sample Code

AWS 기술 블로그에서 제공하는 샘플 코드 저장소입니다.

[![License: MIT-0](https://img.shields.io/badge/License-MIT--0-yellow.svg)](./LICENSE)
[![AWS](https://img.shields.io/badge/AWS-Tech%20Blog-FF9900?logo=amazon-aws)](https://aws.amazon.com/ko/blogs/tech/)

---

## Table of Contents

- [Overview](#overview)
- [Repository Structure](#repository-structure)
- [Sample Projects](#sample-projects)
  - [bedrock - Amazon Bedrock](#bedrock---amazon-bedrock)
  - [opensearch - Amazon OpenSearch Service](#opensearch---amazon-opensearch-service)
  - [database - Amazon Aurora](#database---amazon-aurora)
  - [iot - AWS IoT Core](#iot---aws-iot-core)
  - [serverless - AWS Lambda](#serverless---aws-lambda)
- [Getting Started](#getting-started)
- [Contributing](#contributing)
- [Security](#security)
- [License](#license)

---

## Overview

이 저장소는 [AWS 기술 블로그 한국어판](https://aws.amazon.com/ko/blogs/tech/)에 게시된 기술 문서의 샘플 코드를 제공합니다. 각 프로젝트는 독립적으로 실행 가능하며, 해당 블로그 게시물에서 상세한 구현 가이드를 확인할 수 있습니다.

### Tech Stack

| Category | Technologies |
|----------|-------------|
| Infrastructure as Code | AWS CDK (TypeScript) |
| AI/ML | Amazon Bedrock, LangChain |
| Database | Amazon Aurora MySQL, Amazon DynamoDB, Amazon Redshift |
| Search | Amazon OpenSearch Service |
| Languages | Python, TypeScript, Java, SQL |

---

## Repository Structure

```
kr-tech-blog-sample-code/
├── bedrock/                    # Amazon Bedrock 관련 샘플
│   ├── amazon-bedrock-travel-agent/
│   ├── bedrock-mcp-agent-cdk/
│   ├── bedrock_aurora_mysql/
│   ├── cdk_bedrock_rag_chatbot/
│   └── smart-agent-db-architecture/
├── opensearch/                 # Amazon OpenSearch Service 관련 샘플
│   ├── opensearch_custom_plugin/
│   └── opensearch_ltr/
├── database/                   # Amazon Aurora 관련 샘플
│   └── auroramysql-task-automation-tip/
├── iot/                        # AWS IoT Core 관련 샘플
│   └── cdk_iot_dev/
└── serverless/                 # AWS Lambda 관련 샘플
    └── lambda_layers/
```

---

## Sample Projects

### bedrock - Amazon Bedrock

Amazon Bedrock을 활용한 생성형 AI 애플리케이션 구축 샘플입니다.

| Project | Description | Tech Stack | Blog |
|---------|-------------|------------|------|
| [amazon-bedrock-travel-agent](./bedrock/amazon-bedrock-travel-agent) | Bedrock Agent를 활용한 여행 예약 에이전트 | CDK, Python | [Link](https://aws.amazon.com/ko/blogs/tech/amazon-bedrock-agent-30mins-travel-reservation/) |
| [cdk_bedrock_rag_chatbot](./bedrock/cdk_bedrock_rag_chatbot) | Bedrock Knowledge Base를 활용한 멀티모달 RAG 챗봇 | CDK, Python, Streamlit | [Link](https://aws.amazon.com/ko/blogs/tech/practical-guide-for-bedrock-kb-multimodal-chatbot/) |
| [bedrock-mcp-agent-cdk](./bedrock/bedrock-mcp-agent-cdk) | Bedrock Agents와 MCP(Model Context Protocol) 통합 | CDK, TypeScript, Lambda | [Link](https://aws-blogs-prod.amazon.com/tech/amazon-bedrock-agents-mcp-model-context-protocol/) |
| [bedrock_aurora_mysql](./bedrock/bedrock_aurora_mysql) | Bedrock을 활용한 Aurora MySQL 운영 자동화 | Python, Boto3 | [Link](https://aws.amazon.com/ko/blogs/tech/auroramysql-monitoring-with-amazonbedrock/) |
| [smart-agent-db-architecture](./bedrock/smart-agent-db-architecture) | Agentic AI를 위한 데이터베이스 설계 | Python, SQL, DynamoDB | [Link](https://aws.amazon.com/ko/blogs/tech/smart-agent-db-architecture/) |

### opensearch - Amazon OpenSearch Service

Amazon OpenSearch Service 검색 최적화 및 플러그인 개발 샘플입니다.

| Project | Description | Tech Stack | Blog |
|---------|-------------|------------|------|
| [opensearch_custom_plugin](./opensearch/opensearch_custom_plugin) | OpenSearch 커스텀 플러그인 개발 가이드 | Java, Gradle | [Link](https://aws.amazon.com/ko/blogs/tech/applying-amazon-opensearch-service-custom-plugin/) |
| [opensearch_ltr](./opensearch/opensearch_ltr) | Learning to Rank 플러그인을 활용한 검색 품질 개선 | Python, Jupyter | Link |

### database - Amazon Aurora

Amazon Aurora 운영 자동화 및 배포 전략 샘플입니다.

| Project | Description | Tech Stack | Blog |
|---------|-------------|------------|------|
| [auroramysql-task-automation-tip](./database/auroramysql-task-automation-tip) | Aurora MySQL Blue/Green 배포 자동화 스크립트 | Python, Boto3 | [Link](https://aws.amazon.com/ko/blogs/tech/auroramysql-task-automation-tip/) |

### iot - AWS IoT Core

AWS IoT Core 기반 디바이스 관리 및 데이터 수집 샘플입니다.

| Project | Description | Tech Stack | Blog |
|---------|-------------|------------|------|
| [cdk_iot_dev](./iot/cdk_iot_dev) | CDK를 활용한 FMS(Fleet Management System) 자동화 | CDK, TypeScript | [Link](https://aws.amazon.com/ko/blogs/tech/aws-cloud-development-kit-cdk-42dot-fleet-management-systemfms-automation/) |

### serverless - AWS Lambda

AWS Lambda 개발을 위한 유틸리티 및 레이어 샘플입니다.

| Project | Description | Tech Stack |
|---------|-------------|------------|
| [lambda_layers](./serverless/lambda_layers) | Lambda Layer 패키지 (PyIceberg, PyMySQL) | Python |

---

## Getting Started

### Prerequisites

- AWS CLI v2 configured with appropriate credentials
- Node.js 18.x or later (for CDK projects)
- Python 3.9 or later (for Python projects)
- Java 11 or later (for OpenSearch plugin)

### Quick Start

각 프로젝트 디렉토리의 README.md에서 상세한 설치 및 실행 가이드를 확인하세요.

```bash
# Clone the repository
git clone https://github.com/aws-samples/kr-tech-blog-sample-code.git
cd kr-tech-blog-sample-code

# Navigate to the project
cd <category>/<project-name>

# Follow the project-specific README
```

---

## Contributing

기여를 환영합니다. 자세한 내용은 [CONTRIBUTING.md](./CONTRIBUTING.md)를 참조하세요.

1. 이 저장소를 Fork 합니다.
2. Feature 브랜치를 생성합니다. (`git checkout -b feature/amazing-feature`)
3. 변경사항을 커밋합니다. (`git commit -m 'Add amazing feature'`)
4. 브랜치에 Push 합니다. (`git push origin feature/amazing-feature`)
5. Pull Request를 생성합니다.

---

## Security

보안 이슈 발견 시 [CONTRIBUTING.md](./CONTRIBUTING.md#security-issue-notifications)의 안내에 따라 보고해 주세요.

---

## License

This project is licensed under the MIT-0 License. See the [LICENSE](./LICENSE) file for details.

---

## Additional Resources

- [AWS 기술 블로그 한국어판](https://aws.amazon.com/ko/blogs/tech/)
- [AWS Documentation](https://docs.aws.amazon.com/)
- [AWS CDK Documentation](https://docs.aws.amazon.com/cdk/)
- [Amazon Bedrock Documentation](https://docs.aws.amazon.com/bedrock/)

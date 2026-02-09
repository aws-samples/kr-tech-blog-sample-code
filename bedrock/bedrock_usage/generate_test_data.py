#!/usr/bin/env python3
"""테스트 데이터 생성 - IAM Role 기반 Bedrock API 호출 (다중 리전 지원)"""

import boto3
import json
import time
import random
from datetime import datetime

# 계정 ID 동적 가져오기
ACCOUNT_ID = boto3.client("sts").get_caller_identity()["Account"]

# 테스트 시나리오 정의 (다중 리전, 다중 모델)
TEST_SCENARIOS = [
    # ===== US East 리전 (11개 모델 지원) =====
    {
        "type": "role",
        "name": "CustomerServiceApp-BedrockRole",
        "role_arn": f"arn:aws:iam::{ACCOUNT_ID}:role/CustomerServiceApp-BedrockRole",
        "region": "us-east-1",
        "model": "us.anthropic.claude-3-haiku-20240307-v1:0",
        "calls": random.randint(1, 5),
        "prompt": "고객 문의: 배송이 지연되고 있습니다.",
    },
    {
        "type": "role",
        "name": "DataAnalysisApp-BedrockRole",
        "role_arn": f"arn:aws:iam::{ACCOUNT_ID}:role/DataAnalysisApp-BedrockRole",
        "region": "us-east-1",
        "model": "us.anthropic.claude-sonnet-4-5-20250929-v1:0",  # Claude 4.5
        "calls": random.randint(1, 5),
        "prompt": "데이터 분석: [1,2,3,4,5]",
    },
    {
        "type": "role",
        "name": "CustomerServiceApp-BedrockRole",
        "role_arn": f"arn:aws:iam::{ACCOUNT_ID}:role/CustomerServiceApp-BedrockRole",
        "region": "us-east-1",
        "model": "us.anthropic.claude-3-7-sonnet-20250219-v1:0",  # Claude 3.7
        "calls": random.randint(1, 5),
        "prompt": "제품 설명을 작성해주세요.",
    },
    {
        "type": "role",
        "name": "DataAnalysisApp-BedrockRole",
        "role_arn": f"arn:aws:iam::{ACCOUNT_ID}:role/DataAnalysisApp-BedrockRole",
        "region": "us-east-1",
        "model": "us.anthropic.claude-opus-4-20250514-v1:0",  # Claude Opus 4
        "calls": random.randint(1, 5),
        "prompt": "복잡한 비즈니스 전략을 수립해주세요.",
    },
    # ===== US West 리전 (17개 모델 지원) =====
    {
        "type": "role",
        "name": "DocumentProcessorApp-BedrockRole",
        "role_arn": f"arn:aws:iam::{ACCOUNT_ID}:role/DocumentProcessorApp-BedrockRole",
        "region": "us-west-2",
        "model": "us.anthropic.claude-sonnet-4-5-20250929-v1:0",  # Claude 4.5
        "calls": random.randint(1, 5),
        "prompt": "문서 요약: AWS 클라우드 서비스",
    },
    {
        "type": "role",
        "name": "DocumentProcessorApp-BedrockRole",
        "role_arn": f"arn:aws:iam::{ACCOUNT_ID}:role/DocumentProcessorApp-BedrockRole",
        "region": "us-west-2",
        "model": "us.anthropic.claude-3-5-haiku-20241022-v1:0",  # Claude 3.5 Haiku
        "calls": random.randint(1, 5),
        "prompt": "짧은 문서 처리",
    },
    # ===== Tokyo 리전 (Cross-Region Inference 포함) =====
    {
        "type": "role",
        "name": "ChatbotApp-BedrockRole",
        "role_arn": f"arn:aws:iam::{ACCOUNT_ID}:role/ChatbotApp-BedrockRole",
        "region": "ap-northeast-1",
        "model": "anthropic.claude-3-haiku-20240307-v1:0",  # Claude 3 Haiku (Direct)
        "calls": random.randint(1, 5),
        "prompt": "こんにちは！今日の天気は？",
    },
    {
        "type": "role",
        "name": "ChatbotApp-BedrockRole",
        "role_arn": f"arn:aws:iam::{ACCOUNT_ID}:role/ChatbotApp-BedrockRole",
        "region": "ap-northeast-1",
        "model": "anthropic.claude-3-5-sonnet-20240620-v1:0",  # Claude 3.5 v1 (Direct)
        "calls": random.randint(1, 5),
        "prompt": "東京の観光スポットを教えて",
    },
    # ===== Seoul 리전 (Cross-Region Inference 포함) =====
    {
        "type": "role",
        "name": "KoreaServiceApp-BedrockRole",
        "role_arn": f"arn:aws:iam::{ACCOUNT_ID}:role/KoreaServiceApp-BedrockRole",
        "region": "ap-northeast-2",
        "model": "anthropic.claude-3-haiku-20240307-v1:0",  # Claude 3 Haiku (Direct)
        "calls": random.randint(1, 5),
        "prompt": "서울 날씨 정보",
    },
    {
        "type": "role",
        "name": "KoreaServiceApp-BedrockRole",
        "role_arn": f"arn:aws:iam::{ACCOUNT_ID}:role/KoreaServiceApp-BedrockRole",
        "region": "ap-northeast-2",
        "model": "anthropic.claude-3-5-sonnet-20240620-v1:0",  # Claude 3.5 v1 (Direct)
        "calls": random.randint(1, 5),
        "prompt": "서울 교통 상황 분석",
    },
    # ===== Singapore 리전 (Cross-Region Inference 포함) =====
    {
        "type": "role",
        "name": "SingaporeAnalyticsApp-BedrockRole",
        "role_arn": f"arn:aws:iam::{ACCOUNT_ID}:role/SingaporeAnalyticsApp-BedrockRole",
        "region": "ap-southeast-1",
        "model": "anthropic.claude-3-haiku-20240307-v1:0",  # Claude 3 Haiku (Direct)
        "calls": random.randint(1, 5),
        "prompt": "Singapore market overview",
    },
    {
        "type": "role",
        "name": "SingaporeAnalyticsApp-BedrockRole",
        "role_arn": f"arn:aws:iam::{ACCOUNT_ID}:role/SingaporeAnalyticsApp-BedrockRole",
        "region": "ap-southeast-1",
        "model": "anthropic.claude-3-5-sonnet-20240620-v1:0",  # Claude 3.5 v1 (Direct)
        "calls": random.randint(1, 5),
        "prompt": "Southeast Asia business trends",
    },
]


def call_bedrock_with_role(scenario):
    """IAM Role을 assume하고 Bedrock API 호출"""

    print(f"\n🔐 Testing: {scenario['name']} (IAM Role)")
    print(f"   Role ARN: {scenario['role_arn']}")
    print(f"   Region: {scenario['region']}")
    print(f"   Model: {scenario['model']}")
    print(f"   Calls: {scenario['calls']}")

    try:
        # STS로 Role assume
        sts_client = boto3.client("sts", region_name="us-east-1")
        assumed_role = sts_client.assume_role(
            RoleArn=scenario["role_arn"],
            RoleSessionName=f"{scenario['name']}-test-session",
        )

        # Assumed role credentials로 Bedrock 클라이언트 생성
        bedrock = boto3.client(
            "bedrock-runtime",
            region_name=scenario["region"],
            aws_access_key_id=assumed_role["Credentials"]["AccessKeyId"],
            aws_secret_access_key=assumed_role["Credentials"]["SecretAccessKey"],
            aws_session_token=assumed_role["Credentials"]["SessionToken"],
        )

        success_count = 0
        for i in range(scenario["calls"]):
            try:
                # Bedrock API 호출
                response = bedrock.invoke_model(
                    modelId=scenario["model"],
                    body=json.dumps(
                        {
                            "anthropic_version": "bedrock-2023-05-31",
                            "max_tokens": 200,
                            "messages": [
                                {"role": "user", "content": scenario["prompt"]}
                            ],
                        }
                    ),
                )

                success_count += 1
                print(f"   ✅ Call {i+1}/{scenario['calls']} succeeded")

                # API rate limit을 고려한 짧은 대기
                time.sleep(0.5)

            except Exception as e:
                print(f"   ❌ Call {i+1}/{scenario['calls']} failed: {e}")

        print(f"   📊 Result: {success_count}/{scenario['calls']} calls succeeded")
        return success_count

    except Exception as e:
        print(f"   ❌ Error: {e}")
        return 0


def main():
    print("=" * 80)
    print("🧪 Bedrock Application Test Data Generator (Multi-Region, IAM Role-based)")
    print("=" * 80)
    print(f"\n⏰ Start Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"📝 Total Scenarios: {len(TEST_SCENARIOS)}")

    # 리전별 분류
    region_stats = {}
    for scenario in TEST_SCENARIOS:
        region = scenario["region"]
        if region not in region_stats:
            region_stats[region] = 0
        region_stats[region] += 1

    print("\n📊 Scenarios by Region:")
    for region, count in region_stats.items():
        print(f"   • {region}: {count} IAM Roles")

    results = {
        "total_scenarios": len(TEST_SCENARIOS),
        "successful_scenarios": 0,
        "total_calls": sum(s["calls"] for s in TEST_SCENARIOS),
        "successful_calls": 0,
        "by_region": {},
    }

    # IAM Role 기반 테스트
    print("\n" + "=" * 80)
    print("IAM Role-based Applications")
    print("=" * 80)

    for scenario in TEST_SCENARIOS:
        success_count = call_bedrock_with_role(scenario)
        if success_count > 0:
            results["successful_scenarios"] += 1
            results["successful_calls"] += success_count

            # 리전별 통계
            region = scenario["region"]
            if region not in results["by_region"]:
                results["by_region"][region] = {"calls": 0}
            results["by_region"][region]["calls"] += success_count

    # 결과 요약
    print("\n" + "=" * 80)
    print("📊 Test Summary")
    print("=" * 80)
    print(
        f"\n✅ Successful Scenarios: {results['successful_scenarios']}/{results['total_scenarios']}"
    )
    print(
        f"✅ Successful API Calls: {results['successful_calls']}/{results['total_calls']}"
    )

    print("\n📊 Results by Region:")
    for region, stats in results["by_region"].items():
        print(f"   • {region}: {stats['calls']} successful calls")

    print(f"\n⏰ End Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    print("\n" + "=" * 80)
    print("💡 Next Steps")
    print("=" * 80)
    print("\n1. Wait 2-3 minutes for Model Invocation Logging to be indexed")
    print("2. Run the tracker to verify application-level cost analysis:")
    print("   streamlit run bedrock_tracker.py")
    print("\n3. Or use CLI version:")
    print("   python bedrock_tracker_cli.py --region <region> --days 7")
    print("\n4. Check the analytics for each region:")
    for region in results["by_region"].keys():
        print(f"   - {region}")
    print("\n" + "=" * 80)


if __name__ == "__main__":
    main()

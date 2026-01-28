#!/usr/bin/env python3
"""
Bedrock Application with RequestMetadata for Usage Tracking
이 애플리케이션은 여러 시나리오에서 Bedrock을 호출하며,
각 호출에 requestMetadata를 포함하여 CloudWatch Logs에서 추적 가능합니다.
"""

import boto3
import json
import time
from datetime import datetime

# Bedrock Runtime 클라이언트 생성
client = boto3.client('bedrock-runtime', region_name='us-east-1')


def invoke_bedrock_with_metadata(
    prompt: str,
    app_name: str,
    app_id: str,
    environment: str,
    team: str,
    cost_center: str,
    tenant_id: str = None,
    user_id: str = None
):
    """
    Bedrock Converse API를 호출하고 requestMetadata를 포함합니다.

    Args:
        prompt: 사용자 프롬프트
        app_name: 애플리케이션 이름
        app_id: 애플리케이션 ID
        environment: 환경 (production, staging, dev)
        team: 팀 이름
        cost_center: 비용 센터 코드
        tenant_id: 테넌트 ID (옵션)
        user_id: 사용자 ID (옵션)

    Returns:
        Bedrock API 응답
    """

    # requestMetadata 구성
    metadata = {
        "application_name": app_name,
        "application_id": app_id,
        "environment": environment,
        "team": team,
        "cost_center": cost_center,
        "timestamp": datetime.now().isoformat()
    }

    # 옵션 필드 추가
    if tenant_id:
        metadata["tenant_id"] = tenant_id
    if user_id:
        metadata["user_id"] = user_id

    print(f"\n{'='*80}")
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Invoking Bedrock")
    print(f"Application: {app_name} ({app_id})")
    print(f"Environment: {environment}")
    print(f"Prompt: {prompt[:50]}...")
    print(f"Metadata: {json.dumps(metadata, indent=2)}")

    try:
        # Bedrock Converse API 호출
        response = client.converse(
            modelId='anthropic.claude-3-haiku-20240307-v1:0',
            messages=[
                {
                    "role": "user",
                    "content": [{"text": prompt}]
                }
            ],
            requestMetadata=metadata
        )

        # 응답 처리
        output_text = response['output']['message']['content'][0]['text']
        input_tokens = response['usage']['inputTokens']
        output_tokens = response['usage']['outputTokens']
        total_tokens = input_tokens + output_tokens

        print(f"\n✅ Success!")
        print(f"Input Tokens: {input_tokens}")
        print(f"Output Tokens: {output_tokens}")
        print(f"Total Tokens: {total_tokens}")
        print(f"Response (first 200 chars): {output_text[:200]}...")
        print(f"{'='*80}\n")

        return response

    except Exception as e:
        print(f"\n❌ Error: {str(e)}")
        print(f"{'='*80}\n")
        raise


def scenario_customer_service():
    """시나리오 1: 고객 서비스 애플리케이션"""
    print("\n" + "="*80)
    print("SCENARIO 1: Customer Service Application")
    print("="*80)

    prompts = [
        "How do I reset my password?",
        "What is your refund policy?",
        "I need help with my order #12345"
    ]

    for i, prompt in enumerate(prompts, 1):
        invoke_bedrock_with_metadata(
            prompt=prompt,
            app_name="CustomerServiceApp",
            app_id="app-001",
            environment="production",
            team="customer-support",
            cost_center="CS-123",
            tenant_id=f"tenant-{100 + i}",
            user_id=f"user-{200 + i}"
        )
        time.sleep(1)  # Rate limiting


def scenario_sales_assistant():
    """시나리오 2: 세일즈 어시스턴트 애플리케이션"""
    print("\n" + "="*80)
    print("SCENARIO 2: Sales Assistant Application")
    print("="*80)

    prompts = [
        "What are the features of your enterprise plan?",
        "Can you compare the basic and premium tiers?"
    ]

    for i, prompt in enumerate(prompts, 1):
        invoke_bedrock_with_metadata(
            prompt=prompt,
            app_name="SalesAssistantApp",
            app_id="app-002",
            environment="production",
            team="sales",
            cost_center="SALES-456",
            tenant_id=f"prospect-{300 + i}",
            user_id=f"sales-rep-{400 + i}"
        )
        time.sleep(1)


def scenario_internal_tools():
    """시나리오 3: 내부 도구 (개발 환경)"""
    print("\n" + "="*80)
    print("SCENARIO 3: Internal Tools (Development)")
    print("="*80)

    prompts = [
        "Generate a SQL query to find all users created in the last 30 days",
        "Write a Python function to validate email addresses"
    ]

    for i, prompt in enumerate(prompts, 1):
        invoke_bedrock_with_metadata(
            prompt=prompt,
            app_name="DeveloperToolsApp",
            app_id="app-003",
            environment="development",
            team="engineering",
            cost_center="ENG-789",
            user_id=f"dev-{500 + i}"
        )
        time.sleep(1)


def scenario_multi_tenant():
    """시나리오 4: 멀티테넌트 SaaS"""
    print("\n" + "="*80)
    print("SCENARIO 4: Multi-Tenant SaaS Application")
    print("="*80)

    # 여러 테넌트의 요청 시뮬레이션
    tenants = [
        {"id": "acme-corp", "name": "ACME Corporation"},
        {"id": "globex-inc", "name": "Globex Inc"},
        {"id": "initech-llc", "name": "Initech LLC"}
    ]

    prompt = "Summarize the key points from our meeting notes"

    for tenant in tenants:
        invoke_bedrock_with_metadata(
            prompt=prompt,
            app_name="DocumentAnalysisApp",
            app_id="app-004",
            environment="production",
            team="product",
            cost_center="PROD-999",
            tenant_id=tenant["id"],
            user_id=f"user-{tenant['id']}-001"
        )
        time.sleep(1)


def main():
    """메인 함수 - 모든 시나리오 실행"""
    print("\n" + "="*80)
    print("🚀 Starting Bedrock Application with RequestMetadata")
    print("="*80)
    print("\nThis application will generate sample requests with different metadata")
    print("to demonstrate usage tracking in CloudWatch Logs.\n")

    print("⚠️  Prerequisites:")
    print("  1. Bedrock Model Invocation Logging must be enabled")
    print("  2. CloudWatch Logs destination configured")
    print("  3. Appropriate IAM permissions for Bedrock API calls\n")

    try:
        # 각 시나리오 실행
        scenario_customer_service()
        scenario_sales_assistant()
        scenario_internal_tools()
        scenario_multi_tenant()

        print("\n" + "="*80)
        print("✅ All scenarios completed successfully!")
        print("="*80)
        print("\n📊 Next Steps:")
        print("  1. Wait 2-3 minutes for logs to appear in CloudWatch")
        print("  2. Go to CloudWatch Logs console")
        print("  3. Select log group: /aws/bedrock/modelinvocations")
        print("  4. Use the CloudWatch Logs Insights queries provided")
        print("="*80 + "\n")

    except Exception as e:
        print(f"\n❌ Error running scenarios: {str(e)}")
        raise


if __name__ == "__main__":
    main()

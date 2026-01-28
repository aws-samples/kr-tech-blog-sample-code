#!/usr/bin/env python3
"""Bedrock 권한 검증 스크립트"""

import boto3
import json
from datetime import datetime

def test_bedrock_permissions():
    """각 리전에서 Bedrock 권한 테스트"""
    
    regions = ['us-east-1', 'us-west-2', 'ap-northeast-1', 'ap-northeast-2', 'ap-southeast-1']
    roles = [
        'CustomerServiceApp-BedrockRole',
        'DataAnalysisApp-BedrockRole', 
        'ChatbotApp-BedrockRole',
        'DocumentProcessorApp-BedrockRole'
    ]
    
    sts = boto3.client('sts')
    account_id = sts.get_caller_identity()['Account']
    
    print("=" * 80)
    print("🔍 Bedrock Multi-Region Permission Verification")
    print("=" * 80)
    print(f"Account ID: {account_id}")
    print(f"Test Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
    
    results = {}
    
    for role_name in roles:
        print(f"Testing role: {role_name}")
        results[role_name] = {}
        
        try:
            # Role assume
            role_arn = f"arn:aws:iam::{account_id}:role/{role_name}"
            assumed_role = sts.assume_role(
                RoleArn=role_arn,
                RoleSessionName=f"test-session-{role_name}"
            )
            
            credentials = assumed_role['Credentials']
            print(f"  ✅ Successfully assumed role: {role_name}")
            
            # 각 리전에서 Bedrock 테스트
            for region in regions:
                try:
                    bedrock = boto3.client(
                        'bedrock',
                        region_name=region,
                        aws_access_key_id=credentials['AccessKeyId'],
                        aws_secret_access_key=credentials['SecretAccessKey'],
                        aws_session_token=credentials['SessionToken']
                    )
                    
                    # Foundation models 조회 시도
                    response = bedrock.list_foundation_models()
                    model_count = len(response.get('modelSummaries', []))
                    
                    results[role_name][region] = {
                        'status': 'success',
                        'models': model_count
                    }
                    print(f"    ✅ {region}: {model_count} models available")
                    
                except Exception as e:
                    results[role_name][region] = {
                        'status': 'error',
                        'error': str(e)
                    }
                    print(f"    ❌ {region}: {str(e)}")
                    
        except Exception as e:
            print(f"  ❌ Failed to assume role {role_name}: {e}")
            for region in regions:
                results[role_name][region] = {
                    'status': 'role_error',
                    'error': str(e)
                }
    
    # 결과 요약
    print("\n" + "=" * 80)
    print("📊 Test Results Summary")
    print("=" * 80)
    
    for role_name, role_results in results.items():
        success_count = sum(1 for r in role_results.values() if r['status'] == 'success')
        total_count = len(regions)
        
        print(f"\n{role_name}: {success_count}/{total_count} regions successful")
        
        for region, result in role_results.items():
            if result['status'] == 'success':
                print(f"  ✅ {region}: {result['models']} models")
            else:
                print(f"  ❌ {region}: {result.get('error', 'Unknown error')}")
    
    return results

if __name__ == "__main__":
    test_bedrock_permissions()

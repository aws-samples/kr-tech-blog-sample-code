#!/usr/bin/env python3
"""다중 리전 Model Invocation Logging 설정"""

import boto3
import json

def setup_logging_for_region(region, bucket_name):
    """특정 리전에 Model Invocation Logging 설정"""
    try:
        bedrock = boto3.client('bedrock', region_name=region)
        
        # 현재 설정 확인
        try:
            current_config = bedrock.get_model_invocation_logging_configuration()
            print(f"  Current config: {current_config.get('loggingConfig', 'None')}")
        except:
            print(f"  No current config")
        
        # 로깅 설정
        response = bedrock.put_model_invocation_logging_configuration(
            loggingConfig={
                's3Config': {
                    'bucketName': bucket_name,
                    'keyPrefix': f'bedrock-logs/'
                }
            }
        )
        
        print(f"  ✅ Logging enabled: s3://{bucket_name}/bedrock-logs/")
        return True
        
    except Exception as e:
        print(f"  ❌ Error: {e}")
        return False

def main():
    regions = ['us-east-1', 'us-west-2', 'ap-northeast-1', 'ap-northeast-2', 'ap-southeast-1']
    account_id = '181136804328'
    
    print("=" * 80)
    print("🔧 Setting up Multi-Region Model Invocation Logging")
    print("=" * 80)
    
    results = {}
    
    for region in regions:
        bucket_name = f'bedrock-logs-{account_id}-{region}'
        print(f"Setting up logging for {region} -> {bucket_name}...")
        results[region] = setup_logging_for_region(region, bucket_name)
    
    print("\n" + "=" * 80)
    print("📋 Summary")
    print("=" * 80)
    
    for region, success in results.items():
        bucket_name = f'bedrock-logs-{account_id}-{region}'
        status = "✅ Success" if success else "❌ Failed"
        print(f"{region}: {status} -> s3://{bucket_name}/bedrock-logs/")

if __name__ == "__main__":
    main()

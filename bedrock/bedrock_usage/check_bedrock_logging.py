#!/usr/bin/env python3
"""다중 리전 Bedrock Model Invocation Logging 설정 확인"""

import boto3

def check_logging_for_region(region):
    """특정 리전의 Model Invocation Logging 설정 확인"""
    try:
        bedrock = boto3.client('bedrock', region_name=region)
        config = bedrock.get_model_invocation_logging_configuration()

        s3_config = config.get('loggingConfig', {}).get('s3Config', {})

        if s3_config:
            bucket_name = s3_config.get('bucketName', 'N/A')
            key_prefix = s3_config.get('keyPrefix', 'N/A')

            # 버킷 리전 확인
            bucket_region = 'Unknown'
            if bucket_name != 'N/A':
                try:
                    s3 = boto3.client('s3')
                    location = s3.get_bucket_location(Bucket=bucket_name)
                    bucket_region = location['LocationConstraint'] or 'us-east-1'
                except Exception as e:
                    bucket_region = f'Error: {str(e)[:30]}'

            return {
                'enabled': True,
                'bucket': bucket_name,
                'prefix': key_prefix,
                'bucket_region': bucket_region
            }
        else:
            return {
                'enabled': False,
                'bucket': 'Not configured',
                'prefix': 'N/A',
                'bucket_region': 'N/A'
            }

    except Exception as e:
        return {
            'enabled': False,
            'bucket': 'Error',
            'prefix': 'N/A',
            'bucket_region': 'N/A',
            'error': str(e)
        }

def main():
    regions = ['us-east-1', 'us-west-2', 'ap-northeast-1', 'ap-northeast-2', 'ap-southeast-1']

    print("=" * 80)
    print("🔍 Checking Multi-Region Bedrock Model Invocation Logging Configuration")
    print("=" * 80)
    print()

    results = {}

    for region in regions:
        print(f"Checking {region}...")
        results[region] = check_logging_for_region(region)

    print()
    print("=" * 80)
    print("📋 Summary")
    print("=" * 80)
    print()

    for region, config in results.items():
        status = "✅ Enabled" if config['enabled'] else "❌ Not Configured"
        print(f"{region}:")
        print(f"  Status: {status}")
        print(f"  S3 Bucket: {config['bucket']}")
        print(f"  Key Prefix: {config['prefix']}")
        print(f"  Bucket Region: {config['bucket_region']}")

        if 'error' in config:
            print(f"  Error: {config['error']}")

        print()

if __name__ == "__main__":
    main()

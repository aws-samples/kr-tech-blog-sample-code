#!/usr/bin/env python3
"""
Amazon Q Developer 사용자 활동 보고서 S3 설정 스크립트
- S3 버킷 생성 및 권한 설정
- KMS 키 생성 및 권한 설정 (필요시)
- 서비스 연결 역할 확인
- 계정 ID에 관계없이 사용 가능
"""

import boto3
import json
import sys
import time
from typing import Dict, Optional

def get_account_id() -> str:
    """현재 AWS 계정 ID 조회"""
    sts = boto3.client('sts')
    return sts.get_caller_identity()['Account']

def get_current_user_arn() -> str:
    """현재 사용자 ARN 조회"""
    sts = boto3.client('sts')
    return sts.get_caller_identity()['Arn']

def get_current_region() -> str:
    """현재 리전 조회"""
    session = boto3.Session()
    return session.region_name or 'us-east-1'

def check_service_linked_role(account_id: str) -> bool:
    """Amazon Q Developer 서비스 연결 역할 확인"""
    try:
        iam = boto3.client('iam')
        role_name = 'AWSServiceRoleForAmazonQDeveloper'
        iam.get_role(RoleName=role_name)
        print(f"✅ 서비스 연결 역할 존재: {role_name}")
        return True
    except iam.exceptions.NoSuchEntityException:
        print("❌ Amazon Q Developer 서비스 연결 역할이 없습니다.")
        print("   콘솔에서 Amazon Q Developer를 한 번 사용하면 자동 생성됩니다.")
        return False
    except Exception as e:
        print(f"⚠️  서비스 연결 역할 확인 실패: {e}")
        return False

def create_kms_key_if_needed(account_id: str, region: str) -> Optional[str]:
    """필요시 KMS 키 생성"""
    try:
        kms = boto3.client('kms', region_name=region)
        
        # 기존 Amazon Q용 KMS 키 검색
        aliases = kms.list_aliases()
        for alias in aliases['Aliases']:
            if 'amazonq' in alias.get('AliasName', '').lower():
                print(f"✅ 기존 Amazon Q KMS 키 발견: {alias['AliasName']}")
                return alias.get('TargetKeyId')
        
        print("🔑 Amazon Q Developer용 KMS 키 생성 중...")
        
        # KMS 키 정책
        key_policy = {
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Sid": "Enable IAM User Permissions",
                    "Effect": "Allow",
                    "Principal": {"AWS": f"arn:aws:iam::{account_id}:root"},
                    "Action": "kms:*",
                    "Resource": "*"
                },
                {
                    "Sid": "Allow Amazon Q Developer Service",
                    "Effect": "Allow",
                    "Principal": {"Service": "q.amazonaws.com"},
                    "Action": [
                        "kms:Decrypt",
                        "kms:GenerateDataKey",
                        "kms:CreateGrant"
                    ],
                    "Resource": "*"
                }
            ]
        }
        
        # KMS 키 생성
        response = kms.create_key(
            Description='Amazon Q Developer encryption key',
            KeyUsage='ENCRYPT_DECRYPT',
            Policy=json.dumps(key_policy)
        )
        
        key_id = response['KeyMetadata']['KeyId']
        
        # 별칭 생성
        alias_name = f'alias/amazonq-developer-{account_id}'
        try:
            kms.create_alias(
                AliasName=alias_name,
                TargetKeyId=key_id
            )
            print(f"✅ KMS 키 생성 완료: {alias_name}")
        except Exception as e:
            print(f"⚠️  KMS 별칭 생성 실패: {e}")
        
        return key_id
        
    except Exception as e:
        print(f"⚠️  KMS 키 생성 실패: {e}")
        return None

def create_s3_bucket(bucket_name: str, region: str) -> bool:
    """S3 버킷 생성"""
    try:
        s3 = boto3.client('s3', region_name=region)
        
        # 버킷 존재 확인
        try:
            s3.head_bucket(Bucket=bucket_name)
            print(f"✅ 버킷 이미 존재: {bucket_name}")
            return True
        except:
            pass
        
        # 버킷 생성
        if region == 'us-east-1':
            s3.create_bucket(Bucket=bucket_name)
        else:
            s3.create_bucket(
                Bucket=bucket_name,
                CreateBucketConfiguration={'LocationConstraint': region}
            )
        
        print(f"✅ S3 버킷 생성 완료: {bucket_name}")
        return True
        
    except Exception as e:
        print(f"❌ S3 버킷 생성 실패: {e}")
        return False

def set_bucket_encryption(bucket_name: str, kms_key_id: Optional[str] = None) -> bool:
    """S3 버킷 암호화 설정"""
    try:
        s3 = boto3.client('s3')
        
        if kms_key_id:
            # KMS 암호화
            encryption_config = {
                'Rules': [{
                    'ApplyServerSideEncryptionByDefault': {
                        'SSEAlgorithm': 'aws:kms',
                        'KMSMasterKeyID': kms_key_id
                    },
                    'BucketKeyEnabled': True
                }]
            }
        else:
            # AES256 암호화
            encryption_config = {
                'Rules': [{
                    'ApplyServerSideEncryptionByDefault': {
                        'SSEAlgorithm': 'AES256'
                    },
                    'BucketKeyEnabled': False
                }]
            }
        
        s3.put_bucket_encryption(
            Bucket=bucket_name,
            ServerSideEncryptionConfiguration=encryption_config
        )
        
        encryption_type = "KMS" if kms_key_id else "AES256"
        print(f"✅ 버킷 암호화 설정 완료: {encryption_type}")
        return True
        
    except Exception as e:
        print(f"⚠️  버킷 암호화 설정 실패: {e}")
        return False

def create_bucket_policy(bucket_name: str, account_id: str, kms_key_id: Optional[str] = None) -> Dict:
    """S3 버킷 정책 생성"""
    statements = [
        {
            "Sid": "AmazonQDeveloperServiceAccess",
            "Effect": "Allow",
            "Principal": {"Service": "q.amazonaws.com"},
            "Action": [
                "s3:PutObject",
                "s3:PutObjectAcl",
                "s3:GetBucketLocation",
                "s3:ListBucket"
            ],
            "Resource": [
                f"arn:aws:s3:::{bucket_name}",
                f"arn:aws:s3:::{bucket_name}/*"
            ]
        },
        {
            "Sid": "AmazonQDeveloperRoleAccess",
            "Effect": "Allow",
            "Principal": {
                "AWS": f"arn:aws:iam::{account_id}:role/aws-service-role/q.amazonaws.com/AWSServiceRoleForAmazonQDeveloper"
            },
            "Action": [
                "s3:PutObject",
                "s3:PutObjectAcl",
                "s3:GetBucketLocation",
                "s3:ListBucket"
            ],
            "Resource": [
                f"arn:aws:s3:::{bucket_name}",
                f"arn:aws:s3:::{bucket_name}/*"
            ]
        }
    ]
    
    # KMS 키가 있으면 KMS 권한 추가
    if kms_key_id:
        statements.append({
            "Sid": "AmazonQDeveloperKMSAccess",
            "Effect": "Allow",
            "Principal": {"Service": "q.amazonaws.com"},
            "Action": [
                "kms:Decrypt",
                "kms:GenerateDataKey"
            ],
            "Resource": f"arn:aws:kms:*:{account_id}:key/{kms_key_id}"
        })
    
    return {
        "Version": "2012-10-17",
        "Statement": statements
    }

def apply_bucket_policy(bucket_name: str, policy: Dict) -> bool:
    """S3 버킷에 정책 적용"""
    try:
        s3 = boto3.client('s3')
        s3.put_bucket_policy(
            Bucket=bucket_name,
            Policy=json.dumps(policy)
        )
        return True
    except Exception as e:
        print(f"❌ 버킷 정책 적용 실패: {e}")
        return False

def setup_reports_bucket(bucket_name: str, account_id: str, region: str, use_kms: bool = False) -> bool:
    """사용자 활동 보고서 버킷 설정"""
    print(f"\n🔧 사용자 활동 보고서 버킷 설정 중: {bucket_name}")
    
    # 1. 버킷 생성
    if not create_s3_bucket(bucket_name, region):
        return False
    
    # 2. KMS 키 생성 (필요시)
    kms_key_id = None
    if use_kms:
        kms_key_id = create_kms_key_if_needed(account_id, region)
    
    # 3. 버킷 암호화 설정
    set_bucket_encryption(bucket_name, kms_key_id)
    
    # 4. 버킷 정책 생성 및 적용
    policy = create_bucket_policy(bucket_name, account_id, kms_key_id)
    if apply_bucket_policy(bucket_name, policy):
        print(f"✅ {bucket_name} 설정 완료")
        return True
    else:
        return False

def cleanup_old_buckets(account_id: str):
    """이전에 생성된 테스트 버킷들 정리"""
    try:
        s3 = boto3.client('s3')
        response = s3.list_buckets()
        
        cleanup_patterns = [
            'amazon-q-developer-data',
            'amazonq-developer-data'
        ]
        
        for bucket in response['Buckets']:
            bucket_name = bucket['Name']
            for pattern in cleanup_patterns:
                if pattern in bucket_name and account_id in bucket_name:
                    try:
                        # 버킷 비우기
                        s3_resource = boto3.resource('s3')
                        bucket_obj = s3_resource.Bucket(bucket_name)
                        bucket_obj.objects.all().delete()
                        
                        # 버킷 삭제
                        s3.delete_bucket(Bucket=bucket_name)
                        print(f"🗑️  이전 데이터 버킷 삭제: {bucket_name}")
                    except Exception as e:
                        print(f"⚠️  버킷 삭제 실패 {bucket_name}: {e}")
                    break
    except Exception as e:
        print(f"⚠️  버킷 정리 실패: {e}")

def main():
    print("🚀 Amazon Q Developer 사용자 활동 보고서 S3 설정")
    print("=" * 60)

    try:
        # 기본 정보 수집
        account_id = get_account_id()
        user_arn = get_current_user_arn()
        region = get_current_region()

        print(f"📋 계정 ID: {account_id}")
        print(f"👤 사용자: {user_arn}")
        print(f"🌍 리전: {region}")

        # 서비스 연결 역할 확인
        print(f"\n🔍 서비스 연결 역할 확인 중...")
        has_service_role = check_service_linked_role(account_id)

        # 이전 데이터 버킷 정리
        print(f"\n🗑️  이전 데이터 버킷 정리 중...")
        cleanup_old_buckets(account_id)

        # 사용자 활동 보고서 버킷 설정
        reports_bucket = f'amazonq-developer-reports-{account_id}'
        athena_bucket = f'qcli-analytics-{account_id}-{region}'

        print(f"\n📊 Amazon Q Developer 사용자 활동 보고서 버킷 설정 중...")
        reports_success = setup_reports_bucket(reports_bucket, account_id, region, use_kms=False)

        # Athena 쿼리 결과 버킷 생성
        print(f"\n📊 Athena 쿼리 결과 버킷 설정 중...")
        athena_success = create_s3_bucket(athena_bucket, region)

        if athena_success:
            # Athena 버킷 암호화 설정
            set_bucket_encryption(athena_bucket, None)

        if reports_success:
            # 결과 요약
            print("\n" + "=" * 60)
            print("📊 설정 결과")
            print("=" * 60)
            print("🎉 Amazon Q Developer 사용자 활동 보고서 설정이 완료되었습니다!")

            print(f"\n📋 생성된 버킷:")
            print(f"   📊 리포트 버킷: {reports_bucket}")
            if athena_success:
                print(f"   📊 Athena 결과 버킷: {athena_bucket}")

            print(f"\n📋 다음 단계:")
            print(f"   1. Athena 분석 환경 구축:")
            print(f"      python setup_qcli_analytics.py --region {region}")
            print(f"")
            print(f"   2. Amazon Q Developer 콘솔 설정:")
            print(f"      - Amazon Q Developer 콘솔로 이동")
            print(f"      - 'Collect granular metrics per user' 활성화")
            print(f"      - S3 버킷: {reports_bucket}")
            print(f"")
            print(f"   3. 대시보드 실행:")
            print(f"      streamlit run bedrock_tracker.py")

            if not has_service_role:
                print(f"\n⚠️  주의사항:")
                print(f"   - 서비스 연결 역할이 없습니다")
                print(f"   - Amazon Q Developer 콘솔을 한 번 방문하여 역할을 생성하세요")
        else:
            print(f"❌ 사용자 활동 보고서 버킷 설정 실패")
            sys.exit(1)

    except Exception as e:
        print(f"❌ 오류 발생: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()

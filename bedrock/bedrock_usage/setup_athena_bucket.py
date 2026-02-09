#!/usr/bin/env python3
"""Athena 분석 환경 통합 설정 스크립트"""

import boto3
import time
from datetime import datetime

REGIONS = {
    "us-east-1": "US East (N. Virginia)",
    "us-west-2": "US West (Oregon)",
    "eu-central-1": "Europe (Frankfurt)",
    "ap-northeast-1": "Asia Pacific (Tokyo)",
    "ap-northeast-2": "Asia Pacific (Seoul)",
    "ap-southeast-1": "Asia Pacific (Singapore)"
}

def get_account_id():
    return boto3.client('sts').get_caller_identity()['Account']

def create_bucket_if_not_exists(s3_client, bucket_name, region):
    """S3 버킷 생성 (존재하지 않는 경우)"""
    try:
        if region == 'us-east-1':
            s3_client.create_bucket(Bucket=bucket_name)
        else:
            s3_client.create_bucket(
                Bucket=bucket_name,
                CreateBucketConfiguration={'LocationConstraint': region}
            )
        print(f"✅ S3 버킷 생성: {bucket_name}")
    except Exception as e:
        if "BucketAlreadyExists" in str(e) or "BucketAlreadyOwnedByYou" in str(e):
            print(f"ℹ️  버킷 존재: {bucket_name}")
        else:
            print(f"❌ 버킷 생성 실패: {e}")
            raise

def create_glue_resource(glue_client, resource_type, name, config):
    """Glue 리소스 생성 (데이터베이스 또는 테이블)"""
    try:
        if resource_type == 'database':
            glue_client.create_database(DatabaseInput=config)
        else:
            glue_client.create_table(**config)
        print(f"✅ Glue {resource_type} 생성: {name}")
    except Exception as e:
        if "AlreadyExistsException" in str(e):
            print(f"ℹ️  {resource_type} 존재: {name}")
        else:
            print(f"❌ {resource_type} 생성 실패: {e}")

def execute_athena_query(athena_client, query, database, output_location):
    """Athena 쿼리 실행"""
    response = athena_client.start_query_execution(
        QueryString=query,
        QueryExecutionContext={'Database': database},
        ResultConfiguration={'OutputLocation': output_location}
    )
    return response['QueryExecutionId']

def wait_for_query(athena_client, query_id, timeout=30):
    """Athena 쿼리 완료 대기"""
    for _ in range(timeout):
        result = athena_client.get_query_execution(QueryExecutionId=query_id)
        status = result['QueryExecution']['Status']['State']
        if status in ['SUCCEEDED', 'FAILED', 'CANCELLED']:
            return status
        time.sleep(1)
    return 'TIMEOUT'

def setup_region(region, account_id):
    """단일 리전 설정"""
    print(f"\n🔧 {region} 설정 중...")
    
    # 클라이언트 생성
    s3 = boto3.client('s3', region_name=region)
    glue = boto3.client('glue', region_name=region)
    athena = boto3.client('athena', region_name=region)
    bedrock = boto3.client('bedrock', region_name=region)
    
    # 버킷명
    analytics_bucket = f"bedrock-analytics-{account_id}-{region}"
    
    # 1. Analytics 버킷 생성
    create_bucket_if_not_exists(s3, analytics_bucket, region)
    
    # 2. Glue 데이터베이스 생성
    create_glue_resource(glue, 'database', 'bedrock_analytics', {
        'Name': 'bedrock_analytics',
        'Description': f'Bedrock Model Invocation Logs Database for {region}'
    })
    
    # 3. Bedrock 로깅 설정 확인 및 테이블 생성
    try:
        config = bedrock.get_model_invocation_logging_configuration()
        s3_config = config.get('loggingConfig', {}).get('s3Config', {})
        
        if s3_config:
            log_bucket = s3_config.get('bucketName')
            log_prefix = s3_config.get('keyPrefix', 'bedrock-logs/')
            
            # Glue 테이블 생성
            create_glue_resource(glue, 'table', 'bedrock_invocation_logs', {
                'DatabaseName': 'bedrock_analytics',
                'TableInput': {
                    'Name': 'bedrock_invocation_logs',
                    'StorageDescriptor': {
                        'Columns': [
                            {'Name': 'timestamp', 'Type': 'string'},
                            {'Name': 'accountid', 'Type': 'string'},
                            {'Name': 'region', 'Type': 'string'},
                            {'Name': 'modelid', 'Type': 'string'},
                            {'Name': 'identity', 'Type': 'struct<arn:string>'},
                            {'Name': 'input', 'Type': 'struct<inputTokenCount:int>'},
                            {'Name': 'output', 'Type': 'struct<outputTokenCount:int>'}
                        ],
                        'Location': f's3://{log_bucket}/{log_prefix}',
                        'InputFormat': 'org.apache.hadoop.mapred.TextInputFormat',
                        'OutputFormat': 'org.apache.hadoop.hive.ql.io.HiveIgnoreKeyTextOutputFormat',
                        'SerdeInfo': {'SerializationLibrary': 'org.openx.data.jsonserde.JsonSerDe'}
                    },
                    'PartitionKeys': [
                        {'Name': 'year', 'Type': 'string'},
                        {'Name': 'month', 'Type': 'string'},
                        {'Name': 'day', 'Type': 'string'}
                    ]
                }
            })
            
            # 4. 파티션 추가
            today = datetime.now()
            year, month, day = today.strftime('%Y'), today.strftime('%m'), today.strftime('%d')
            
            partition_query = f"""
            ALTER TABLE bedrock_analytics.bedrock_invocation_logs 
            ADD IF NOT EXISTS PARTITION (year='{year}', month='{month}', day='{day}')
            LOCATION 's3://{log_bucket}/AWSLogs/{account_id}/BedrockModelInvocationLogs/{region}/{year}/{month}/{day}/'
            """
            
            query_id = execute_athena_query(athena, partition_query, 'bedrock_analytics', 
                                          f's3://{analytics_bucket}/query-results/')
            print(f"✅ 파티션 추가: {year}/{month}/{day}")
            
            # 5. 데이터 테스트
            test_query = f"""
            SELECT COUNT(*) as total_records
            FROM bedrock_analytics.bedrock_invocation_logs 
            WHERE year='{year}' AND month='{month}' AND day='{day}'
            """
            
            query_id = execute_athena_query(athena, test_query, 'bedrock_analytics',
                                          f's3://{analytics_bucket}/query-results/')
            
            if wait_for_query(athena, query_id) == 'SUCCEEDED':
                results = athena.get_query_results(QueryExecutionId=query_id)
                if len(results['ResultSet']['Rows']) > 1:
                    count = results['ResultSet']['Rows'][1]['Data'][0]['VarCharValue']
                    print(f"✅ 데이터 확인: {count}개 레코드")
                else:
                    print(f"⚠️  데이터 없음")
            else:
                print(f"❌ 테스트 쿼리 실패")
                
        else:
            print(f"⚠️  Bedrock 로깅 미설정")
            
    except Exception as e:
        print(f"⚠️  Bedrock 설정 확인 실패: {e}")

def main():
    print("🚀 Athena 분석 환경 통합 설정 시작...")
    
    account_id = get_account_id()
    print(f"📝 Account ID: {account_id}")
    
    for region in REGIONS.keys():
        try:
            setup_region(region, account_id)
        except Exception as e:
            print(f"❌ {region} 설정 실패: {e}")
    
    print("\n✅ 모든 설정 완료!")

if __name__ == "__main__":
    main()

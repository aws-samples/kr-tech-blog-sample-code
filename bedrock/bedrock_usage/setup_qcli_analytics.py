#!/usr/bin/env python3
"""
Amazon Q CLI 사용량 추적을 위한 설정 스크립트

이 스크립트는 다음을 설정합니다:
1. S3 버킷 생성 (사용자 활동 리포트 저장 및 Athena 쿼리 결과)
2. Glue 데이터베이스 생성
3. Athena 테이블 생성 (CSV 리포트 분석용)
"""

import boto3
import json
import time
from datetime import datetime
import sys


def setup_qcli_analytics(region="us-east-1", recreate_table=False, create_sample_data=False):
    """Amazon Q CLI 분석 환경 설정

    Args:
        region: AWS 리전
        recreate_table: True일 경우 기존 테이블 삭제 후 재생성
        create_sample_data: True일 경우 샘플 데이터 생성
    """

    print(f"🚀 Amazon Q CLI Analytics 설정 시작 (리전: {region})")
    print("=" * 80)

    # AWS 클라이언트 초기화
    sts = boto3.client("sts", region_name=region)
    s3 = boto3.client("s3", region_name=region)
    athena = boto3.client("athena", region_name=region)
    glue = boto3.client("glue", region_name=region)

    # 계정 ID 가져오기
    account_id = sts.get_caller_identity()["Account"]
    print(f"📋 AWS 계정 ID: {account_id}")

    # 버킷 이름 설정
    reports_bucket = f"amazonq-developer-reports-{account_id}"
    athena_results_bucket = f"qcli-analytics-{account_id}-{region}"

    print(f"📦 리포트 버킷: {reports_bucket}")
    print(f"📦 Athena 결과 버킷: {athena_results_bucket}")

    # Step 1: S3 버킷 생성
    print("\n" + "=" * 80)
    print("📦 Step 1: S3 버킷 생성")
    print("=" * 80)

    buckets_to_create = [
        (reports_bucket, "Amazon Q Developer 사용자 활동 리포트"),
        (athena_results_bucket, "Athena 쿼리 결과"),
    ]

    for bucket_name, purpose in buckets_to_create:
        try:
            print(f"\n📁 버킷 생성 중: {bucket_name} ({purpose})")

            # 버킷이 이미 존재하는지 확인
            try:
                s3.head_bucket(Bucket=bucket_name)
                print(f"  ✅ 버킷이 이미 존재합니다: {bucket_name}")
                continue
            except:
                pass

            # 버킷 생성
            if region == "us-east-1":
                s3.create_bucket(Bucket=bucket_name)
            else:
                s3.create_bucket(
                    Bucket=bucket_name,
                    CreateBucketConfiguration={"LocationConstraint": region}
                )

            # 버킷 버저닝 활성화
            s3.put_bucket_versioning(
                Bucket=bucket_name,
                VersioningConfiguration={"Status": "Enabled"}
            )

            print(f"  ✅ 버킷 생성 완료: {bucket_name}")

        except Exception as e:
            print(f"  ❌ 버킷 생성 실패: {str(e)}")
            if "BucketAlreadyOwnedByYou" in str(e):
                print(f"  ℹ️  버킷이 이미 존재합니다")
            else:
                raise

    # Step 2: Glue 데이터베이스 생성
    print("\n" + "=" * 80)
    print("🗄️  Step 2: Glue 데이터베이스 생성")
    print("=" * 80)

    database_name = "qcli_analytics"

    try:
        glue.create_database(
            DatabaseInput={
                'Name': database_name,
                'Description': 'Amazon Q CLI 사용량 분석 데이터베이스'
            }
        )
        print(f"✅ Glue 데이터베이스 생성 완료: {database_name}")
    except Exception as e:
        if "AlreadyExistsException" in str(e):
            print(f"ℹ️  데이터베이스가 이미 존재합니다: {database_name}")
        else:
            print(f"❌ 데이터베이스 생성 실패: {str(e)}")

    # Step 3: Amazon Q Developer CSV 리포트용 테이블 생성
    print("\n" + "=" * 80)
    print("📊 Step 3: Amazon Q Developer CSV 리포트용 테이블 생성")
    print("=" * 80)

    # Step 3-1: 기존 테이블 삭제 (재생성 옵션이 활성화된 경우)
    if recreate_table:
        print(f"  🗑️  기존 테이블 삭제 중...")
        drop_table_query = f"DROP TABLE IF EXISTS {database_name}.qcli_user_activity_reports;"

        try:
            response = athena.start_query_execution(
                QueryString=drop_table_query,
                QueryExecutionContext={'Database': database_name},
                ResultConfiguration={
                    'OutputLocation': f's3://{athena_results_bucket}/setup-results/'
                }
            )

            query_execution_id = response['QueryExecutionId']

            # 쿼리 완료 대기
            for i in range(30):
                result = athena.get_query_execution(QueryExecutionId=query_execution_id)
                status = result['QueryExecution']['Status']['State']

                if status == 'SUCCEEDED':
                    print(f"  ✅ 기존 테이블 삭제 완료")
                    break
                elif status in ['FAILED', 'CANCELLED']:
                    error_msg = result['QueryExecution']['Status'].get('StateChangeReason', 'Unknown error')
                    print(f"  ⚠️  테이블 삭제 실패: {error_msg}")
                    break

                time.sleep(1)

        except Exception as e:
            print(f"  ⚠️  테이블 삭제 실패: {str(e)}")

    # Step 3-2: 테이블 생성 (실제 AWS CSV 스키마)
    create_csv_table_query = f"""
    CREATE EXTERNAL TABLE IF NOT EXISTS {database_name}.qcli_user_activity_reports (
        UserId STRING,
        Date STRING,
        Chat_AICodeLines INT,
        Chat_MessagesInteracted INT,
        Chat_MessagesSent INT,
        CodeFix_AcceptanceEventCount INT,
        CodeFix_AcceptedLines INT,
        CodeFix_GeneratedLines INT,
        CodeFix_GenerationEventCount INT,
        CodeReview_FailedEventCount INT,
        CodeReview_FindingsCount INT,
        CodeReview_SucceededEventCount INT,
        Dev_AcceptanceEventCount INT,
        Dev_AcceptedLines INT,
        Dev_GeneratedLines INT,
        Dev_GenerationEventCount INT,
        DocGeneration_AcceptedFileUpdates INT,
        DocGeneration_AcceptedFilesCreations INT,
        DocGeneration_AcceptedLineAdditions INT,
        DocGeneration_AcceptedLineUpdates INT,
        DocGeneration_EventCount INT,
        DocGeneration_RejectedFileCreations INT,
        DocGeneration_RejectedFileUpdates INT,
        DocGeneration_RejectedLineAdditions INT,
        DocGeneration_RejectedLineUpdates INT,
        InlineChat_AcceptanceEventCount INT,
        InlineChat_AcceptedLineAdditions INT,
        InlineChat_AcceptedLineDeletions INT,
        InlineChat_DismissalEventCount INT,
        InlineChat_DismissedLineAdditions INT,
        InlineChat_DismissedLineDeletions INT,
        InlineChat_RejectedLineAdditions INT,
        InlineChat_RejectedLineDeletions INT,
        InlineChat_RejectionEventCount INT,
        InlineChat_TotalEventCount INT,
        Inline_AICodeLines INT,
        Inline_AcceptanceCount INT,
        Inline_SuggestionsCount INT,
        TestGeneration_AcceptedLines INT,
        TestGeneration_AcceptedTests INT,
        TestGeneration_EventCount INT,
        TestGeneration_GeneratedLines INT,
        TestGeneration_GeneratedTests INT,
        Transformation_EventCount INT,
        Transformation_LinesGenerated INT,
        Transformation_LinesIngested INT
    )
    ROW FORMAT SERDE 'org.apache.hadoop.hive.serde2.OpenCSVSerde'
    WITH SERDEPROPERTIES (
       'separatorChar' = ',',
       'quoteChar' = '"',
       'escapeChar' = '\\\\'
    )
    LOCATION 's3://{reports_bucket}/user-activity-reports/AWSLogs/{account_id}/QDeveloperLogs/by_user_analytic/{region}/'
    TBLPROPERTIES ('skip.header.line.count'='1');
    """

    try:
        response = athena.start_query_execution(
            QueryString=create_csv_table_query,
            QueryExecutionContext={'Database': database_name},
            ResultConfiguration={
                'OutputLocation': f's3://{athena_results_bucket}/setup-results/'
            }
        )

        query_execution_id = response['QueryExecutionId']
        print(f"  ⏳ Athena 쿼리 실행 중... (ID: {query_execution_id})")

        # 쿼리 완료 대기 (최대 60초)
        max_wait = 60
        for i in range(max_wait):
            result = athena.get_query_execution(QueryExecutionId=query_execution_id)
            status = result['QueryExecution']['Status']['State']

            if status == 'SUCCEEDED':
                print(f"  ✅ CSV 리포트 테이블 생성 완료")
                break
            elif status in ['FAILED', 'CANCELLED']:
                error_msg = result['QueryExecution']['Status'].get('StateChangeReason', 'Unknown error')
                print(f"  ❌ 테이블 생성 실패: {error_msg}")
                break

            time.sleep(1)

    except Exception as e:
        print(f"❌ CSV 테이블 생성 실패: {str(e)}")

    # Step 3-3: 테이블 검증
    print("\n  🔍 테이블 검증 중...")
    try:
        verify_query = f"SELECT COUNT(*) as row_count FROM {database_name}.qcli_user_activity_reports LIMIT 1;"

        response = athena.start_query_execution(
            QueryString=verify_query,
            QueryExecutionContext={'Database': database_name},
            ResultConfiguration={
                'OutputLocation': f's3://{athena_results_bucket}/verify-results/'
            }
        )

        query_execution_id = response['QueryExecutionId']

        # 쿼리 완료 대기
        for i in range(30):
            result = athena.get_query_execution(QueryExecutionId=query_execution_id)
            status = result['QueryExecution']['Status']['State']

            if status == 'SUCCEEDED':
                # 결과 가져오기
                results = athena.get_query_results(QueryExecutionId=query_execution_id)
                if len(results['ResultSet']['Rows']) > 1:
                    row_count = results['ResultSet']['Rows'][1]['Data'][0].get('VarCharValue', '0')
                    print(f"  ✅ 테이블 검증 완료 - 현재 데이터: {row_count}행")
                else:
                    print(f"  ✅ 테이블 검증 완료 - 데이터 없음")
                break
            elif status in ['FAILED', 'CANCELLED']:
                error_msg = result['QueryExecution']['Status'].get('StateChangeReason', 'Unknown error')
                print(f"  ⚠️  테이블 검증 실패: {error_msg}")
                break

            time.sleep(1)

    except Exception as e:
        print(f"  ⚠️  테이블 검증 실패: {str(e)}")

    # Step 4: 샘플 데이터 생성 (옵션)
    if create_sample_data:
        print("\n" + "=" * 80)
        print("📊 Step 4: 샘플 데이터 생성")
        print("=" * 80)

        try:
            import csv
            import io
            from datetime import timedelta

            # 샘플 데이터 생성 (최근 7일간)
            sample_data = []
            today = datetime.now()

            users = [
                "user1@example.com",
                "user2@example.com",
                "user3@example.com",
                "developer1@company.com",
                "developer2@company.com"
            ]

            for days_ago in range(7, 0, -1):
                date = (today - timedelta(days=days_ago)).strftime("%Y-%m-%d")

                for user in users:
                    row = {
                        'date': date,
                        'user_id': user,
                        'request_count': 10 + (days_ago * 5),
                        'agentic_request_count': 3 + days_ago,
                        'code_suggestion_count': 15 + (days_ago * 3),
                        'cli_request_count': 5 + days_ago,
                        'ide_request_count': 5 + (days_ago * 2),
                        'total_tokens': 1000 + (days_ago * 100)
                    }
                    sample_data.append(row)

            # CSV 생성
            csv_buffer = io.StringIO()
            fieldnames = ['date', 'user_id', 'request_count', 'agentic_request_count',
                          'code_suggestion_count', 'cli_request_count', 'ide_request_count',
                          'total_tokens']

            writer = csv.DictWriter(csv_buffer, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(sample_data)

            # S3에 업로드
            csv_content = csv_buffer.getvalue()
            s3_key = f"sample-user-activity-{today.strftime('%Y%m%d')}.csv"

            s3.put_object(
                Bucket=reports_bucket,
                Key=s3_key,
                Body=csv_content.encode('utf-8'),
                ContentType='text/csv'
            )
            print(f"  ✅ 샘플 CSV 파일 업로드 완료: {s3_key}")
            print(f"  📊 생성된 데이터: 최근 7일, {len(users)}명 사용자, {len(sample_data)}개 레코드")

        except Exception as e:
            print(f"  ⚠️  샘플 데이터 생성 실패: {str(e)}")

    # 완료 메시지
    print("\n" + "=" * 80)
    print("✨ 설정 완료!")
    print("=" * 80)
    print(f"""
📌 생성된 리소스:
  - 리포트 버킷: {reports_bucket}
  - Athena 결과 버킷: {athena_results_bucket}
  - Glue 데이터베이스: {database_name}
  - Athena 테이블:
      • {database_name}.qcli_user_activity_reports

📋 다음 단계:
  1. Amazon Q Developer 콘솔에서 "Collect granular metrics per user" 활성화
  2. 사용자 활동 리포트 S3 버킷으로 {reports_bucket} 지정
  3. 대시보드 실행:
     streamlit run bedrock_tracker.py

💡 테스트용 샘플 데이터:
  - 샘플 데이터가 필요하면: python setup_qcli_analytics.py --sample-data
  - 또는: python create_sample_qcli_data.py

⚠️  참고사항:
  - CSV 리포트는 매일 자정(UTC)에 생성됩니다
  - Athena 쿼리 비용이 발생할 수 있습니다
  - 테이블 위치: s3://{reports_bucket}/
    """)

    return {
        'reports_bucket': reports_bucket,
        'athena_results_bucket': athena_results_bucket,
        'database_name': database_name,
        'region': region
    }


def main():
    import argparse

    parser = argparse.ArgumentParser(
        description='Amazon Q CLI Analytics 환경 설정',
        epilog='''
사용 예시:
  # 기본 설정
  python setup_qcli_analytics.py

  # 테이블 재생성
  python setup_qcli_analytics.py --recreate-table

  # 샘플 데이터 생성
  python setup_qcli_analytics.py --sample-data

  # 모든 옵션 사용
  python setup_qcli_analytics.py --region us-east-1 --recreate-table --sample-data
        ''',
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument('--region', default='us-east-1',
                        help='AWS 리전 (기본값: us-east-1)')
    parser.add_argument('--recreate-table', action='store_true',
                        help='기존 테이블 삭제 후 재생성')
    parser.add_argument('--sample-data', action='store_true',
                        help='테스트용 샘플 데이터 생성')

    args = parser.parse_args()

    try:
        setup_qcli_analytics(
            region=args.region,
            recreate_table=args.recreate_table,
            create_sample_data=args.sample_data
        )
    except Exception as e:
        print(f"\n❌ 오류 발생: {str(e)}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
Amazon Q CLI 테스트용 샘플 데이터 생성 스크립트
"""

import boto3
from datetime import datetime, timedelta
import csv
import io

def create_sample_qcli_data(region="us-east-1"):
    """샘플 Amazon Q CLI 사용자 활동 데이터 생성"""

    print("🚀 Amazon Q CLI 샘플 데이터 생성 시작")
    print("=" * 80)

    # AWS 클라이언트
    s3 = boto3.client("s3", region_name=region)
    sts = boto3.client("sts", region_name=region)

    account_id = sts.get_caller_identity()["Account"]
    bucket_name = f"amazonq-developer-reports-{account_id}"

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

    try:
        s3.put_object(
            Bucket=bucket_name,
            Key=s3_key,
            Body=csv_content.encode('utf-8'),
            ContentType='text/csv'
        )
        print(f"✅ 샘플 CSV 파일 업로드 완료:")
        print(f"   s3://{bucket_name}/{s3_key}")
        print(f"\n📊 생성된 데이터:")
        print(f"   - 기간: 최근 7일")
        print(f"   - 사용자 수: {len(users)}명")
        print(f"   - 총 레코드: {len(sample_data)}개")
        print(f"\n💡 이제 Streamlit 대시보드를 실행하여 데이터를 확인하세요:")
        print(f"   streamlit run bedrock_tracker.py")

    except Exception as e:
        print(f"❌ 업로드 실패: {str(e)}")
        raise


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description='Amazon Q CLI 샘플 데이터 생성')
    parser.add_argument('--region', default='us-east-1', help='AWS 리전')

    args = parser.parse_args()

    try:
        create_sample_qcli_data(region=args.region)
    except Exception as e:
        print(f"\n❌ 오류 발생: {str(e)}")
        import traceback
        traceback.print_exc()

#!/usr/bin/env python3
"""
CLI 버전의 Bedrock Usage Tracker - Athena 기반
터미널에서 사용 가능한 다양한 분석 기능 제공
"""

import boto3
import pandas as pd
from datetime import datetime, timedelta
import argparse
import time
from typing import Dict
import logging
from pathlib import Path
import json
import sys

# S3 로그 분석기 임포트
from qcli_s3_analyzer import QCliS3LogAnalyzer

# 로깅 설정
def setup_logger():
    """디버깅용 로거 설정"""
    log_dir = Path(__file__).parent / 'log'
    log_dir.mkdir(exist_ok=True)

    log_filename = log_dir / f"bedrock_tracker_cli_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"

    logger = logging.getLogger('BedrockTrackerCLI')
    logger.setLevel(logging.DEBUG)

    # 파일 핸들러
    file_handler = logging.FileHandler(log_filename, encoding='utf-8')
    file_handler.setLevel(logging.DEBUG)

    # 포맷 설정
    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(funcName)s:%(lineno)d - %(message)s'
    )
    file_handler.setFormatter(formatter)

    logger.addHandler(file_handler)
    logger.info(f"Logger initialized. Log file: {log_filename}")

    return logger

# 글로벌 로거
logger = setup_logger()

# AWS Bedrock 모델 가격 테이블 (리전별)
# 참고: 최신 가격은 https://aws.amazon.com/bedrock/pricing/ 에서 확인하세요
# 가격은 USD 기준이며, 1000 토큰당 가격입니다
MODEL_PRICING = {
    # 기본 가격 (대부분의 리전에 적용)
    "default": {
        # Claude 3 모델
        "claude-3-haiku-20240307": {"input": 0.00025, "output": 0.00125},
        "claude-3-sonnet-20240229": {"input": 0.003, "output": 0.015},
        "claude-3-opus-20240229": {"input": 0.015, "output": 0.075},
        # Claude 3.5 모델
        "claude-3-5-haiku-20241022": {"input": 0.0008, "output": 0.004},
        "claude-3-5-sonnet-20240620": {"input": 0.003, "output": 0.015},
        "claude-3-5-sonnet-20241022": {"input": 0.003, "output": 0.015},
        # Claude 3.7 모델
        "claude-3-7-sonnet-20250219": {"input": 0.003, "output": 0.015},
        # Claude 4 모델
        "claude-sonnet-4-20250514": {"input": 0.003, "output": 0.015},
        "claude-sonnet-4-5-20250929": {"input": 0.003, "output": 0.015},
        "claude-opus-4-20250514": {"input": 0.015, "output": 0.075},
        "claude-opus-4-1-20250808": {"input": 0.015, "output": 0.075},
    },
    # US East (N. Virginia) - us-east-1
    "us-east-1": {
        "claude-3-haiku-20240307": {"input": 0.00025, "output": 0.00125},
        "claude-3-sonnet-20240229": {"input": 0.003, "output": 0.015},
        "claude-3-opus-20240229": {"input": 0.015, "output": 0.075},
        "claude-3-5-haiku-20241022": {"input": 0.0008, "output": 0.004},
        "claude-3-5-sonnet-20240620": {"input": 0.003, "output": 0.015},
        "claude-3-5-sonnet-20241022": {"input": 0.003, "output": 0.015},
        "claude-3-7-sonnet-20250219": {"input": 0.003, "output": 0.015},
        "claude-sonnet-4-20250514": {"input": 0.003, "output": 0.015},
        "claude-sonnet-4-5-20250929": {"input": 0.003, "output": 0.015},
        "claude-opus-4-20250514": {"input": 0.015, "output": 0.075},
        "claude-opus-4-1-20250808": {"input": 0.015, "output": 0.075},
    },
    # US West (Oregon) - us-west-2
    "us-west-2": {
        "claude-3-haiku-20240307": {"input": 0.00025, "output": 0.00125},
        "claude-3-sonnet-20240229": {"input": 0.003, "output": 0.015},
        "claude-3-opus-20240229": {"input": 0.015, "output": 0.075},
        "claude-3-5-haiku-20241022": {"input": 0.0008, "output": 0.004},
        "claude-3-5-sonnet-20240620": {"input": 0.003, "output": 0.015},
        "claude-3-5-sonnet-20241022": {"input": 0.003, "output": 0.015},
        "claude-3-7-sonnet-20250219": {"input": 0.003, "output": 0.015},
        "claude-sonnet-4-20250514": {"input": 0.003, "output": 0.015},
        "claude-sonnet-4-5-20250929": {"input": 0.003, "output": 0.015},
        "claude-opus-4-20250514": {"input": 0.015, "output": 0.075},
        "claude-opus-4-1-20250808": {"input": 0.015, "output": 0.075},
    },
    # Europe (Frankfurt) - eu-central-1
    "eu-central-1": {
        "claude-3-haiku-20240307": {"input": 0.00025, "output": 0.00125},
        "claude-3-sonnet-20240229": {"input": 0.003, "output": 0.015},
        "claude-3-opus-20240229": {"input": 0.015, "output": 0.075},
        "claude-3-5-haiku-20241022": {"input": 0.0008, "output": 0.004},
        "claude-3-5-sonnet-20240620": {"input": 0.003, "output": 0.015},
        "claude-3-5-sonnet-20241022": {"input": 0.003, "output": 0.015},
        "claude-3-7-sonnet-20250219": {"input": 0.003, "output": 0.015},
        "claude-sonnet-4-20250514": {"input": 0.003, "output": 0.015},
        "claude-sonnet-4-5-20250929": {"input": 0.003, "output": 0.015},
        "claude-opus-4-20250514": {"input": 0.015, "output": 0.075},
        "claude-opus-4-1-20250808": {"input": 0.015, "output": 0.075},
    },
    # Asia Pacific (Tokyo) - ap-northeast-1
    "ap-northeast-1": {
        "claude-3-haiku-20240307": {"input": 0.00025, "output": 0.00125},
        "claude-3-sonnet-20240229": {"input": 0.003, "output": 0.015},
        "claude-3-opus-20240229": {"input": 0.015, "output": 0.075},
        "claude-3-5-haiku-20241022": {"input": 0.0008, "output": 0.004},
        "claude-3-5-sonnet-20240620": {"input": 0.003, "output": 0.015},
        "claude-3-5-sonnet-20241022": {"input": 0.003, "output": 0.015},
        "claude-3-7-sonnet-20250219": {"input": 0.003, "output": 0.015},
        "claude-sonnet-4-20250514": {"input": 0.003, "output": 0.015},
        "claude-sonnet-4-5-20250929": {"input": 0.003, "output": 0.015},
        "claude-opus-4-20250514": {"input": 0.015, "output": 0.075},
        "claude-opus-4-1-20250808": {"input": 0.015, "output": 0.075},
    },
    # Asia Pacific (Seoul) - ap-northeast-2
    "ap-northeast-2": {
        "claude-3-haiku-20240307": {"input": 0.00025, "output": 0.00125},
        "claude-3-sonnet-20240229": {"input": 0.003, "output": 0.015},
        "claude-3-opus-20240229": {"input": 0.015, "output": 0.075},
        "claude-3-5-haiku-20241022": {"input": 0.0008, "output": 0.004},
        "claude-3-5-sonnet-20240620": {"input": 0.003, "output": 0.015},
        "claude-3-5-sonnet-20241022": {"input": 0.003, "output": 0.015},
        "claude-3-7-sonnet-20250219": {"input": 0.003, "output": 0.015},
        "claude-sonnet-4-20250514": {"input": 0.003, "output": 0.015},
        "claude-sonnet-4-5-20250929": {"input": 0.003, "output": 0.015},
        "claude-opus-4-20250514": {"input": 0.015, "output": 0.075},
        "claude-opus-4-1-20250808": {"input": 0.015, "output": 0.075},
    },
    # Asia Pacific (Singapore) - ap-southeast-1
    "ap-southeast-1": {
        "claude-3-haiku-20240307": {"input": 0.00025, "output": 0.00125},
        "claude-3-sonnet-20240229": {"input": 0.003, "output": 0.015},
        "claude-3-opus-20240229": {"input": 0.015, "output": 0.075},
        "claude-3-5-haiku-20241022": {"input": 0.0008, "output": 0.004},
        "claude-3-5-sonnet-20240620": {"input": 0.003, "output": 0.015},
        "claude-3-5-sonnet-20241022": {"input": 0.003, "output": 0.015},
        "claude-3-7-sonnet-20250219": {"input": 0.003, "output": 0.015},
        "claude-sonnet-4-20250514": {"input": 0.003, "output": 0.015},
        "claude-sonnet-4-5-20250929": {"input": 0.003, "output": 0.015},
        "claude-opus-4-20250514": {"input": 0.015, "output": 0.075},
        "claude-opus-4-1-20250808": {"input": 0.015, "output": 0.075},
    },
}

# 리전 설정
REGIONS = {
    "us-east-1": "US East (N. Virginia)",
    "us-west-2": "US West (Oregon)",
    "eu-central-1": "Europe (Frankfurt)",
    "ap-northeast-1": "Asia Pacific (Tokyo)",
    "ap-northeast-2": "Asia Pacific (Seoul)",
    "ap-southeast-1": "Asia Pacific (Singapore)",
}

def get_model_cost(model_id: str, input_tokens: int, output_tokens: int, region: str = "default") -> float:
    """모델별 비용 계산 (리전별 가격 반영)

    Args:
        model_id: Bedrock 모델 ID (예: us.anthropic.claude-3-haiku-20240307-v1:0)
        input_tokens: 입력 토큰 수
        output_tokens: 출력 토큰 수
        region: AWS 리전 (예: us-east-1, ap-northeast-2)

    Returns:
        float: 계산된 비용 (USD)
    """
    logger.debug(
        f"Calculating cost for model: {model_id}, input: {input_tokens}, output: {output_tokens}, region: {region}"
    )

    # 모델 ID에서 모델명 추출 (예: us.anthropic.claude-3-haiku-20240307-v1:0 -> claude-3-haiku-20240307)
    model_name = model_id.split('.')[-1].split('-v')[0] if '.' in model_id else model_id

    # 리전별 가격 테이블 선택 (해당 리전이 없으면 default 사용)
    region_pricing = MODEL_PRICING.get(region, MODEL_PRICING["default"])

    # 가격 테이블에서 모델 찾기
    for key, pricing in region_pricing.items():
        if key in model_name:
            # 가격은 1000 토큰당 가격이므로 1000으로 나눔
            cost = (input_tokens * pricing["input"] / 1000) + (
                output_tokens * pricing["output"] / 1000
            )
            logger.debug(f"Model: {key}, Region: {region}, Cost: ${cost:.6f}")
            return cost

    # 기본 가격 (Claude 3 Haiku)
    logger.warning(f"Unknown model: {model_id}, using default pricing (Claude 3 Haiku)")
    default_pricing = MODEL_PRICING["default"]["claude-3-haiku-20240307"]
    default_cost = (input_tokens * default_pricing["input"] / 1000) + (
        output_tokens * default_pricing["output"] / 1000
    )
    return default_cost


class BedrockAthenaTracker:
    def __init__(self, region='us-east-1'):
        logger.info(f"Initializing BedrockAthenaTracker with region: {region}")
        self.region = region
        self.athena = boto3.client('athena', region_name=region)
        sts_client = boto3.client('sts', region_name=region)
        self.account_id = sts_client.get_caller_identity()['Account']
        # bedrock_tracker.py와 동일한 버킷명 사용
        self.results_bucket = f'bedrock-analytics-{self.account_id}-{self.region}'
        logger.info(f"Account ID: {self.account_id}, Results bucket: {self.results_bucket}")

    def get_current_logging_config(self) -> Dict:
        """현재 설정된 Model Invocation Logging 정보 조회"""
        logger.info("Getting current logging configuration")
        try:
            bedrock = boto3.client('bedrock', region_name=self.region)
            response = bedrock.get_model_invocation_logging_configuration()

            if 'loggingConfig' in response:
                config = response['loggingConfig']

                if 's3Config' in config:
                    result = {
                        'type': 's3',
                        'bucket': config['s3Config'].get('bucketName', ''),
                        'prefix': config['s3Config'].get('keyPrefix', ''),
                        'status': 'enabled'
                    }
                    logger.info(f"Logging config: {result}")
                    return result

            logger.warning("Logging is disabled")
            return {'status': 'disabled'}

        except Exception as e:
            logger.error(f"Error getting logging config: {str(e)}")
            return {'status': 'error', 'error': str(e)}

    def execute_athena_query(self, query: str, database: str = 'bedrock_analytics') -> pd.DataFrame:
        """Athena 쿼리 실행 및 결과 반환"""
        logger.info(f"Executing Athena query on database: {database}")
        logger.debug(f"Query: {query}")

        try:
            response = self.athena.start_query_execution(
                QueryString=query,
                QueryExecutionContext={'Database': database},
                ResultConfiguration={
                    'OutputLocation': f's3://{self.results_bucket}/query-results/'
                }
            )

            query_id = response['QueryExecutionId']
            logger.info(f"Query execution started: {query_id}")

            max_wait = 60
            for i in range(max_wait):
                result = self.athena.get_query_execution(QueryExecutionId=query_id)
                status = result['QueryExecution']['Status']['State']

                if status == 'SUCCEEDED':
                    logger.info(f"Query succeeded in {i+1} seconds")
                    break
                elif status in ['FAILED', 'CANCELLED']:
                    error = result['QueryExecution']['Status'].get('StateChangeReason', 'Unknown error')
                    logger.error(f"Query failed: {error}")
                    raise Exception(f"Query failed: {error}")

                time.sleep(1)
            else:
                logger.error("Query timeout")
                raise Exception("Query timeout")

            result_response = self.athena.get_query_results(QueryExecutionId=query_id)

            columns = [col['Label'] for col in result_response['ResultSet']['ResultSetMetadata']['ColumnInfo']]
            rows = []

            for row in result_response['ResultSet']['Rows'][1:]:
                row_data = [field.get('VarCharValue', '') for field in row['Data']]
                rows.append(row_data)

            df = pd.DataFrame(rows, columns=columns)
            logger.info(f"Query returned {len(df)} rows")
            return df

        except Exception as e:
            logger.error(f"Athena query execution failed: {str(e)}")
            print(f"❌ Athena 쿼리 실행 실패: {str(e)}", file=sys.stderr)
            return pd.DataFrame()

    def get_total_summary(self, start_date: datetime, end_date: datetime, arn_pattern: str = None) -> Dict:
        """전체 요약 통계"""
        logger.info(f"Getting total summary from {start_date} to {end_date}, arn_pattern={arn_pattern}")

        arn_filter = f"AND identity.arn LIKE '%{arn_pattern}%'" if arn_pattern else ""

        query = f"""
        SELECT
            COUNT(*) as total_calls,
            SUM(CAST(input.inputTokenCount AS BIGINT)) as total_input_tokens,
            SUM(CAST(output.outputTokenCount AS BIGINT)) as total_output_tokens
        FROM bedrock_invocation_logs
        WHERE CAST(CONCAT(year, '-', LPAD(month, 2, '0'), '-', LPAD(day, 2, '0')) AS DATE)
            BETWEEN DATE '{start_date.strftime('%Y-%m-%d')}' AND DATE '{end_date.strftime('%Y-%m-%d')}'
            {arn_filter}
        """

        df = self.execute_athena_query(query)

        if not df.empty:
            result = {
                'total_calls': int(df.iloc[0]['total_calls']) if df.iloc[0]['total_calls'] else 0,
                'total_input_tokens': int(df.iloc[0]['total_input_tokens']) if df.iloc[0]['total_input_tokens'] else 0,
                'total_output_tokens': int(df.iloc[0]['total_output_tokens']) if df.iloc[0]['total_output_tokens'] else 0,
                'total_cost_usd': 0.0
            }
            logger.info(f"Total summary: {result}")
            return result
        else:
            logger.warning("No data found for summary")
            return {'total_calls': 0, 'total_input_tokens': 0, 'total_output_tokens': 0, 'total_cost_usd': 0.0}

    def get_user_cost_analysis(self, start_date: datetime, end_date: datetime, arn_pattern: str = None) -> pd.DataFrame:
        """사용자별 비용 분석"""
        logger.info(f"Getting user cost analysis from {start_date} to {end_date}, arn_pattern={arn_pattern}")

        arn_filter = f"AND identity.arn LIKE '%{arn_pattern}%'" if arn_pattern else ""

        query = f"""
        SELECT
            CASE
                WHEN identity.arn LIKE '%assumed-role%' THEN
                    regexp_extract(identity.arn, 'assumed-role/([^/]+)')
                WHEN identity.arn LIKE '%user%' THEN
                    regexp_extract(identity.arn, 'user/([^/]+)')
                ELSE 'Unknown'
            END as user_or_app,
            COUNT(*) as call_count,
            SUM(CAST(input.inputTokenCount AS BIGINT)) as total_input_tokens,
            SUM(CAST(output.outputTokenCount AS BIGINT)) as total_output_tokens
        FROM bedrock_invocation_logs
        WHERE CAST(CONCAT(year, '-', LPAD(month, 2, '0'), '-', LPAD(day, 2, '0')) AS DATE)
            BETWEEN DATE '{start_date.strftime('%Y-%m-%d')}' AND DATE '{end_date.strftime('%Y-%m-%d')}'
            {arn_filter}
        GROUP BY identity.arn
        ORDER BY call_count DESC
        """

        return self.execute_athena_query(query)

    def get_user_app_detail_analysis(self, start_date: datetime, end_date: datetime, arn_pattern: str = None) -> pd.DataFrame:
        """유저별 애플리케이션별 상세 분석"""
        logger.info(f"Getting user-app detail analysis from {start_date} to {end_date}, arn_pattern={arn_pattern}")

        arn_filter = f"AND identity.arn LIKE '%{arn_pattern}%'" if arn_pattern else ""

        query = f"""
        SELECT
            CASE
                WHEN identity.arn LIKE '%assumed-role%' THEN
                    regexp_extract(identity.arn, 'assumed-role/([^/]+)')
                WHEN identity.arn LIKE '%user%' THEN
                    regexp_extract(identity.arn, 'user/([^/]+)')
                ELSE 'Unknown'
            END as user_or_app,
            regexp_extract(modelId, '([^/]+)$') as model_name,
            COUNT(*) as call_count,
            SUM(CAST(input.inputTokenCount AS BIGINT)) as total_input_tokens,
            SUM(CAST(output.outputTokenCount AS BIGINT)) as total_output_tokens
        FROM bedrock_invocation_logs
        WHERE CAST(CONCAT(year, '-', LPAD(month, 2, '0'), '-', LPAD(day, 2, '0')) AS DATE)
            BETWEEN DATE '{start_date.strftime('%Y-%m-%d')}' AND DATE '{end_date.strftime('%Y-%m-%d')}'
            {arn_filter}
        GROUP BY identity.arn, modelId
        ORDER BY user_or_app, call_count DESC
        """

        return self.execute_athena_query(query)

    def get_model_usage_stats(self, start_date: datetime, end_date: datetime, arn_pattern: str = None) -> pd.DataFrame:
        """모델별 사용 통계"""
        logger.info(f"Getting model usage stats from {start_date} to {end_date}, arn_pattern={arn_pattern}")

        arn_filter = f"AND identity.arn LIKE '%{arn_pattern}%'" if arn_pattern else ""

        query = f"""
        SELECT
            regexp_extract(modelId, '([^/]+)$') as model_name,
            COUNT(*) as call_count,
            AVG(CAST(input.inputTokenCount AS DOUBLE)) as avg_input_tokens,
            AVG(CAST(output.outputTokenCount AS DOUBLE)) as avg_output_tokens,
            SUM(CAST(input.inputTokenCount AS BIGINT)) as total_input_tokens,
            SUM(CAST(output.outputTokenCount AS BIGINT)) as total_output_tokens
        FROM bedrock_invocation_logs
        WHERE CAST(CONCAT(year, '-', LPAD(month, 2, '0'), '-', LPAD(day, 2, '0')) AS DATE)
            BETWEEN DATE '{start_date.strftime('%Y-%m-%d')}' AND DATE '{end_date.strftime('%Y-%m-%d')}'
            {arn_filter}
        GROUP BY modelId
        ORDER BY call_count DESC
        """

        return self.execute_athena_query(query)

    def get_daily_usage_pattern(self, start_date: datetime, end_date: datetime, arn_pattern: str = None) -> pd.DataFrame:
        """일별 사용 패턴"""
        logger.info(f"Getting daily usage pattern from {start_date} to {end_date}, arn_pattern={arn_pattern}")

        arn_filter = f"AND identity.arn LIKE '%{arn_pattern}%'" if arn_pattern else ""

        query = f"""
        SELECT
            year, month, day,
            COUNT(*) as call_count,
            SUM(CAST(input.inputTokenCount AS BIGINT)) as total_input_tokens,
            SUM(CAST(output.outputTokenCount AS BIGINT)) as total_output_tokens
        FROM bedrock_invocation_logs
        WHERE CAST(CONCAT(year, '-', LPAD(month, 2, '0'), '-', LPAD(day, 2, '0')) AS DATE)
            BETWEEN DATE '{start_date.strftime('%Y-%m-%d')}' AND DATE '{end_date.strftime('%Y-%m-%d')}'
            {arn_filter}
        GROUP BY year, month, day
        ORDER BY year, month, day
        """

        return self.execute_athena_query(query)

    def get_hourly_usage_pattern(self, start_date: datetime, end_date: datetime, arn_pattern: str = None) -> pd.DataFrame:
        """시간별 사용 패턴 - timestamp에서 hour 추출"""
        logger.info(f"Getting hourly usage pattern from {start_date} to {end_date}, arn_pattern={arn_pattern}")

        arn_filter = f"AND identity.arn LIKE '%{arn_pattern}%'" if arn_pattern else ""

        query = f"""
        SELECT
            year,
            month,
            day,
            date_format(from_iso8601_timestamp(timestamp), '%H') as hour,
            COUNT(*) as call_count,
            SUM(CAST(input.inputTokenCount AS BIGINT)) as total_input_tokens,
            SUM(CAST(output.outputTokenCount AS BIGINT)) as total_output_tokens
        FROM bedrock_invocation_logs
        WHERE CAST(CONCAT(year, '-', LPAD(month, 2, '0'), '-', LPAD(day, 2, '0')) AS DATE)
            BETWEEN DATE '{start_date.strftime('%Y-%m-%d')}' AND DATE '{end_date.strftime('%Y-%m-%d')}'
            {arn_filter}
        GROUP BY year, month, day, date_format(from_iso8601_timestamp(timestamp), '%H')
        ORDER BY year, month, day, date_format(from_iso8601_timestamp(timestamp), '%H')
        """

        return self.execute_athena_query(query)


# QCli 토큰 사용량 추정 상수
# 기준: 영어 단어 1.4토큰, 4글자당 5토큰
# 코드 1줄 평균 60-80문자 = 약 75-100토큰
QCLI_TOKEN_ESTIMATION = {
    "conservative": {  # 보수적 추정 (짧은 코드/간단한 질문)
        "chat_message_input": 100,
        "chat_message_output": 300,
        "chat_code_line": 50,
        "inline_suggestion": 40,
        "inline_code_line": 50,
        "dev_event_input": 400,
        "dev_event_output": 600,
        "test_event_input": 300,
        "test_event_output": 500,
        "doc_event_input": 200,
        "doc_event_output": 400,
    },
    "average": {  # 평균 추정 (일반적인 사용) - 권장
        "chat_message_input": 150,
        "chat_message_output": 500,
        "chat_code_line": 75,
        "inline_suggestion": 60,
        "inline_code_line": 75,
        "dev_event_input": 600,
        "dev_event_output": 1000,
        "test_event_input": 450,
        "test_event_output": 750,
        "doc_event_input": 350,
        "doc_event_output": 600,
    },
    "optimistic": {  # 낙관적 추정 (복잡한 코드/긴 대화)
        "chat_message_input": 200,
        "chat_message_output": 800,
        "chat_code_line": 100,
        "inline_suggestion": 80,
        "inline_code_line": 100,
        "dev_event_input": 1000,
        "dev_event_output": 1500,
        "test_event_input": 600,
        "test_event_output": 1000,
        "doc_event_input": 500,
        "doc_event_output": 800,
    }
}


class QCliAthenaTracker:
    """Amazon Q CLI 사용량 추적을 위한 Athena 쿼리 클래스"""

    def __init__(self, region='us-east-1'):
        logger.info(f"Initializing QCliAthenaTracker with region: {region}")
        self.region = region
        self.athena = boto3.client("athena", region_name=region)
        sts_client = boto3.client("sts", region_name=region)
        self.account_id = sts_client.get_caller_identity()["Account"]
        self.results_bucket = f"amazonq-developer-reports-{self.account_id}"
        logger.info(
            f"Account ID: {self.account_id}, Results bucket: {self.results_bucket}"
        )

    def execute_athena_query(
        self, query: str, database: str = "qcli_analytics"
    ) -> pd.DataFrame:
        """Athena 쿼리 실행 및 결과 반환"""
        logger.info(f"Executing Athena query on database: {database}")
        logger.debug(f"Query: {query}")

        try:
            # 쿼리 실행
            response = self.athena.start_query_execution(
                QueryString=query,
                QueryExecutionContext={"Database": database},
                ResultConfiguration={
                    "OutputLocation": f"s3://{self.results_bucket}/query-results/"
                },
            )

            query_id = response["QueryExecutionId"]
            logger.info(f"Query execution started: {query_id}")

            # 쿼리 완료 대기
            max_wait = 60
            for i in range(max_wait):
                result = self.athena.get_query_execution(QueryExecutionId=query_id)
                status = result["QueryExecution"]["Status"]["State"]

                if status == "SUCCEEDED":
                    logger.info(f"Query succeeded in {i+1} seconds")
                    break
                elif status in ["FAILED", "CANCELLED"]:
                    error = result["QueryExecution"]["Status"].get(
                        "StateChangeReason", "Unknown error"
                    )
                    logger.error(f"Query failed: {error}")
                    raise Exception(f"Query failed: {error}")

                time.sleep(1)
            else:
                logger.error("Query timeout")
                raise Exception("Query timeout")

            # 결과 조회
            result_response = self.athena.get_query_results(QueryExecutionId=query_id)

            # DataFrame으로 변환
            columns = [
                col["Label"]
                for col in result_response["ResultSet"]["ResultSetMetadata"][
                    "ColumnInfo"
                ]
            ]
            rows = []

            for row in result_response["ResultSet"]["Rows"][1:]:  # 헤더 제외
                row_data = [field.get("VarCharValue", "") for field in row["Data"]]
                rows.append(row_data)

            df = pd.DataFrame(rows, columns=columns)
            logger.info(f"Query returned {len(df)} rows")
            return df

        except Exception as e:
            logger.error(f"Athena query execution failed: {str(e)}")
            print(f"❌ Athena 쿼리 실행 실패: {str(e)}", file=sys.stderr)
            return pd.DataFrame()

    def get_total_summary(
        self, start_date: datetime, end_date: datetime, user_pattern: str = None
    ) -> Dict:
        """전체 요약 통계 - Amazon Q Developer CSV 리포트 기반"""
        logger.info(
            f"Getting QCli total summary from {start_date} to {end_date}, user_pattern={user_pattern}"
        )

        user_filter = f"AND UserId LIKE '%{user_pattern}%'" if user_pattern else ""

        # 실제 AWS CSV 메트릭 사용:
        # - Chat_MessagesSent: 채팅 메시지 수
        # - Inline_SuggestionsCount: 인라인 코드 제안 수
        # - Chat_MessagesInteracted: 사용자 상호작용 메트릭
        query = f"""
        SELECT
            COUNT(DISTINCT UserId) as unique_users,
            COUNT(DISTINCT Date) as active_days,
            SUM(CAST(Chat_MessagesSent AS BIGINT)) as total_chat_messages,
            SUM(CAST(Inline_SuggestionsCount AS BIGINT)) as total_inline_suggestions,
            SUM(CAST(Inline_AcceptanceCount AS BIGINT)) as total_inline_acceptances,
            SUM(CAST(Chat_AICodeLines AS BIGINT)) as total_chat_code_lines,
            SUM(CAST(Inline_AICodeLines AS BIGINT)) as total_inline_code_lines,
            SUM(CAST(Dev_GenerationEventCount AS BIGINT)) as total_dev_events,
            SUM(CAST(TestGeneration_EventCount AS BIGINT)) as total_test_events
        FROM qcli_user_activity_reports
        WHERE parse_datetime(Date, 'MM-dd-yyyy') BETWEEN parse_datetime('{start_date.strftime('%m-%d-%Y')}', 'MM-dd-yyyy')
            AND parse_datetime('{end_date.strftime('%m-%d-%Y')}', 'MM-dd-yyyy')
            {user_filter}
        """

        df = self.execute_athena_query(query)

        if not df.empty and df.iloc[0]["unique_users"]:
            result = {
                "unique_users": (
                    int(df.iloc[0]["unique_users"])
                    if df.iloc[0]["unique_users"]
                    else 0
                ),
                "active_days": (
                    int(df.iloc[0]["active_days"]) if df.iloc[0]["active_days"] else 0
                ),
                "total_chat_messages": (
                    int(df.iloc[0]["total_chat_messages"])
                    if df.iloc[0]["total_chat_messages"]
                    else 0
                ),
                "total_inline_suggestions": (
                    int(df.iloc[0]["total_inline_suggestions"])
                    if df.iloc[0]["total_inline_suggestions"]
                    else 0
                ),
                "total_inline_acceptances": (
                    int(df.iloc[0]["total_inline_acceptances"])
                    if df.iloc[0]["total_inline_acceptances"]
                    else 0
                ),
                "total_chat_code_lines": (
                    int(df.iloc[0]["total_chat_code_lines"])
                    if df.iloc[0]["total_chat_code_lines"]
                    else 0
                ),
                "total_inline_code_lines": (
                    int(df.iloc[0]["total_inline_code_lines"])
                    if df.iloc[0]["total_inline_code_lines"]
                    else 0
                ),
                "total_dev_events": (
                    int(df.iloc[0]["total_dev_events"])
                    if df.iloc[0]["total_dev_events"]
                    else 0
                ),
                "total_test_events": (
                    int(df.iloc[0]["total_test_events"])
                    if df.iloc[0]["total_test_events"]
                    else 0
                ),
            }
            logger.info(f"QCli total summary: {result}")
            return result
        else:
            logger.warning("No data found for summary")
            return {
                "unique_users": 0,
                "active_days": 0,
                "total_chat_messages": 0,
                "total_inline_suggestions": 0,
                "total_inline_acceptances": 0,
                "total_chat_code_lines": 0,
                "total_inline_code_lines": 0,
                "total_dev_events": 0,
                "total_test_events": 0,
            }

    def get_user_usage_analysis(
        self, start_date: datetime, end_date: datetime, user_pattern: str = None
    ) -> pd.DataFrame:
        """사용자별 사용량 분석"""
        logger.info(
            f"Getting QCli user usage analysis from {start_date} to {end_date}, user_pattern={user_pattern}"
        )

        user_filter = f"AND UserId LIKE '%{user_pattern}%'" if user_pattern else ""

        query = f"""
        SELECT
            UserId as user_id,
            SUM(CAST(Chat_MessagesSent AS BIGINT)) as total_chat_messages,
            SUM(CAST(Inline_SuggestionsCount AS BIGINT)) as total_inline_suggestions,
            SUM(CAST(Inline_AcceptanceCount AS BIGINT)) as total_inline_acceptances,
            SUM(CAST(Chat_AICodeLines AS BIGINT)) as total_chat_code_lines,
            SUM(CAST(Inline_AICodeLines AS BIGINT)) as total_inline_code_lines,
            SUM(CAST(Dev_GenerationEventCount AS BIGINT)) as total_dev_events,
            SUM(CAST(TestGeneration_EventCount AS BIGINT)) as total_test_events,
            SUM(CAST(DocGeneration_EventCount AS BIGINT)) as total_doc_events,
            COUNT(DISTINCT Date) as active_days,
            MIN(Date) as first_activity,
            MAX(Date) as last_activity
        FROM qcli_user_activity_reports
        WHERE parse_datetime(Date, 'MM-dd-yyyy') BETWEEN parse_datetime('{start_date.strftime('%m-%d-%Y')}', 'MM-dd-yyyy')
            AND parse_datetime('{end_date.strftime('%m-%d-%Y')}', 'MM-dd-yyyy')
            {user_filter}
        GROUP BY UserId
        ORDER BY total_chat_messages DESC
        """

        return self.execute_athena_query(query)

    def get_daily_usage_pattern(
        self, start_date: datetime, end_date: datetime, user_pattern: str = None
    ) -> pd.DataFrame:
        """일별 사용 패턴"""
        logger.info(
            f"Getting QCli daily usage pattern from {start_date} to {end_date}, user_pattern={user_pattern}"
        )

        user_filter = f"AND UserId LIKE '%{user_pattern}%'" if user_pattern else ""

        query = f"""
        SELECT
            Date as date_str,
            SUM(CAST(Chat_MessagesSent AS BIGINT)) as total_chat_messages,
            SUM(CAST(Inline_SuggestionsCount AS BIGINT)) as total_inline_suggestions,
            SUM(CAST(Inline_AcceptanceCount AS BIGINT)) as total_inline_acceptances,
            SUM(CAST(Chat_AICodeLines AS BIGINT)) as total_chat_code_lines,
            SUM(CAST(Inline_AICodeLines AS BIGINT)) as total_inline_code_lines,
            COUNT(DISTINCT UserId) as unique_users
        FROM qcli_user_activity_reports
        WHERE parse_datetime(Date, 'MM-dd-yyyy') BETWEEN parse_datetime('{start_date.strftime('%m-%d-%Y')}', 'MM-dd-yyyy')
            AND parse_datetime('{end_date.strftime('%m-%d-%Y')}', 'MM-dd-yyyy')
            {user_filter}
        GROUP BY Date
        ORDER BY Date
        """

        return self.execute_athena_query(query)


    def get_feature_usage_stats(
        self, start_date: datetime, end_date: datetime, user_pattern: str = None
    ) -> pd.DataFrame:
        """기능별 사용 통계 (Chat, Inline, Dev, Test, Doc 등)"""
        logger.info(
            f"Getting QCli feature usage stats from {start_date} to {end_date}, user_pattern={user_pattern}"
        )

        user_filter = f"AND UserId LIKE '%{user_pattern}%'" if user_pattern else ""

        query = f"""
        SELECT
            'Chat Messages' as feature_type,
            SUM(CAST(Chat_MessagesSent AS BIGINT)) as total_count,
            COUNT(DISTINCT UserId) as unique_users
        FROM qcli_user_activity_reports
        WHERE parse_datetime(Date, 'MM-dd-yyyy') BETWEEN parse_datetime('{start_date.strftime('%m-%d-%Y')}', 'MM-dd-yyyy')
            AND parse_datetime('{end_date.strftime('%m-%d-%Y')}', 'MM-dd-yyyy')
            {user_filter}
        UNION ALL
        SELECT
            'Inline Suggestions' as feature_type,
            SUM(CAST(Inline_SuggestionsCount AS BIGINT)) as total_count,
            COUNT(DISTINCT UserId) as unique_users
        FROM qcli_user_activity_reports
        WHERE parse_datetime(Date, 'MM-dd-yyyy') BETWEEN parse_datetime('{start_date.strftime('%m-%d-%Y')}', 'MM-dd-yyyy')
            AND parse_datetime('{end_date.strftime('%m-%d-%Y')}', 'MM-dd-yyyy')
            {user_filter}
        UNION ALL
        SELECT
            'Inline Acceptances' as feature_type,
            SUM(CAST(Inline_AcceptanceCount AS BIGINT)) as total_count,
            COUNT(DISTINCT UserId) as unique_users
        FROM qcli_user_activity_reports
        WHERE parse_datetime(Date, 'MM-dd-yyyy') BETWEEN parse_datetime('{start_date.strftime('%m-%d-%Y')}', 'MM-dd-yyyy')
            AND parse_datetime('{end_date.strftime('%m-%d-%Y')}', 'MM-dd-yyyy')
            {user_filter}
        UNION ALL
        SELECT
            '/dev Events' as feature_type,
            SUM(CAST(Dev_GenerationEventCount AS BIGINT)) as total_count,
            COUNT(DISTINCT UserId) as unique_users
        FROM qcli_user_activity_reports
        WHERE parse_datetime(Date, 'MM-dd-yyyy') BETWEEN parse_datetime('{start_date.strftime('%m-%d-%Y')}', 'MM-dd-yyyy')
            AND parse_datetime('{end_date.strftime('%m-%d-%Y')}', 'MM-dd-yyyy')
            {user_filter}
        UNION ALL
        SELECT
            '/test Events' as feature_type,
            SUM(CAST(TestGeneration_EventCount AS BIGINT)) as total_count,
            COUNT(DISTINCT UserId) as unique_users
        FROM qcli_user_activity_reports
        WHERE parse_datetime(Date, 'MM-dd-yyyy') BETWEEN parse_datetime('{start_date.strftime('%m-%d-%Y')}', 'MM-dd-yyyy')
            AND parse_datetime('{end_date.strftime('%m-%d-%Y')}', 'MM-dd-yyyy')
            {user_filter}
        UNION ALL
        SELECT
            '/doc Events' as feature_type,
            SUM(CAST(DocGeneration_EventCount AS BIGINT)) as total_count,
            COUNT(DISTINCT UserId) as unique_users
        FROM qcli_user_activity_reports
        WHERE parse_datetime(Date, 'MM-dd-yyyy') BETWEEN parse_datetime('{start_date.strftime('%m-%d-%Y')}', 'MM-dd-yyyy')
            AND parse_datetime('{end_date.strftime('%m-%d-%Y')}', 'MM-dd-yyyy')
            {user_filter}
        ORDER BY total_count DESC
        """

        return self.execute_athena_query(query)

    def estimate_tokens(self, summary: Dict, estimation_type: str = "average") -> Dict:
        """사용량 데이터로부터 토큰 사용량 추정

        Args:
            summary: get_total_summary()에서 반환된 요약 데이터
            estimation_type: "conservative", "average", "optimistic" 중 선택

        Returns:
            Dict: 추정된 토큰 사용량 정보
        """
        logger.info(f"Estimating tokens with {estimation_type} model")

        if estimation_type not in QCLI_TOKEN_ESTIMATION:
            logger.warning(f"Unknown estimation type: {estimation_type}, using 'average'")
            estimation_type = "average"

        constants = QCLI_TOKEN_ESTIMATION[estimation_type]

        # Input 토큰 추정
        estimated_input_tokens = (
            summary.get("total_chat_messages", 0) * constants["chat_message_input"] +
            summary.get("total_inline_suggestions", 0) * constants["inline_suggestion"] +
            summary.get("total_dev_events", 0) * constants["dev_event_input"] +
            summary.get("total_test_events", 0) * constants["test_event_input"] +
            (summary.get("total_doc_events", 0) if "total_doc_events" in summary else 0) * constants["doc_event_input"]
        )

        # Output 토큰 추정
        estimated_output_tokens = (
            summary.get("total_chat_messages", 0) * constants["chat_message_output"] +
            summary.get("total_chat_code_lines", 0) * constants["chat_code_line"] +
            summary.get("total_inline_code_lines", 0) * constants["inline_code_line"] +
            summary.get("total_inline_acceptances", 0) * constants["inline_suggestion"] +
            summary.get("total_dev_events", 0) * constants["dev_event_output"] +
            summary.get("total_test_events", 0) * constants["test_event_output"] +
            (summary.get("total_doc_events", 0) if "total_doc_events" in summary else 0) * constants["doc_event_output"]
        )

        total_tokens = estimated_input_tokens + estimated_output_tokens

        result = {
            "estimation_type": estimation_type,
            "estimated_input_tokens": int(estimated_input_tokens),
            "estimated_output_tokens": int(estimated_output_tokens),
            "estimated_total_tokens": int(total_tokens),
        }

        logger.info(f"Token estimation result: {result}")
        return result

    def check_official_limits(self, summary: Dict, days_in_period: int) -> Dict:
        """공식 리밋 체크 및 경고 생성

        Args:
            summary: get_total_summary()에서 반환된 요약 데이터
            days_in_period: 조회 기간의 일수

        Returns:
            Dict: 리밋 체크 결과 및 경고
        """
        logger.info("Checking official limits")

        # 공식 문서화된 리밋
        OFFICIAL_LIMITS = {
            "dev_events": 30,  # /dev 명령어: 30회/월
            "transformation_lines": 4000,  # Code Transformation: 4,000줄/월
            # 채팅/인라인: AWS가 공개하지 않음
        }

        # 월간 사용량 추정 (현재 기간을 30일로 환산)
        monthly_factor = 30 / days_in_period if days_in_period > 0 else 1

        dev_events_used = summary.get("total_dev_events", 0)
        dev_events_projected = int(dev_events_used * monthly_factor)

        # Transformation 데이터는 summary에 없을 수 있음 (추후 추가 가능)
        transformation_lines_used = summary.get("total_transformation_lines", 0)
        transformation_lines_projected = int(transformation_lines_used * monthly_factor)

        result = {
            "dev_events": {
                "used": dev_events_used,
                "limit": OFFICIAL_LIMITS["dev_events"],
                "projected_monthly": dev_events_projected,
                "percentage": (dev_events_projected / OFFICIAL_LIMITS["dev_events"] * 100) if OFFICIAL_LIMITS["dev_events"] > 0 else 0,
                "warning": dev_events_projected >= OFFICIAL_LIMITS["dev_events"] * 0.8
            },
            "transformation_lines": {
                "used": transformation_lines_used,
                "limit": OFFICIAL_LIMITS["transformation_lines"],
                "projected_monthly": transformation_lines_projected,
                "percentage": (transformation_lines_projected / OFFICIAL_LIMITS["transformation_lines"] * 100) if OFFICIAL_LIMITS["transformation_lines"] > 0 else 0,
                "warning": transformation_lines_projected >= OFFICIAL_LIMITS["transformation_lines"] * 0.8
            }
        }

        logger.info(f"Limit check result: {result}")
        return result

    def analyze_usage_trends(self, start_date: datetime, end_date: datetime, user_pattern: str = None) -> Dict:
        """사용량 추세 분석 및 이상 감지

        Args:
            start_date: 시작 날짜
            end_date: 종료 날짜
            user_pattern: 사용자 필터 패턴

        Returns:
            Dict: 추세 분석 결과
        """
        logger.info(f"Analyzing usage trends from {start_date} to {end_date}")

        # 일별 사용 패턴 조회
        daily_df = self.get_daily_usage_pattern(start_date, end_date, user_pattern)

        if daily_df.empty:
            return {
                "daily_avg": 0,
                "daily_max": 0,
                "daily_min": 0,
                "anomaly_detected": False
            }

        # 숫자 변환
        for col in ["total_chat_messages", "total_inline_suggestions"]:
            if col in daily_df.columns:
                daily_df[col] = pd.to_numeric(daily_df[col], errors='coerce').fillna(0)

        # 일일 총 활동 계산
        daily_df["total_activity"] = (
            daily_df.get("total_chat_messages", 0) +
            daily_df.get("total_inline_suggestions", 0)
        )

        daily_avg = daily_df["total_activity"].mean()
        daily_max = daily_df["total_activity"].max()
        daily_min = daily_df["total_activity"].min()

        # 이상 감지: 일평균의 3배 초과하는 날이 있는지
        anomaly_threshold = daily_avg * 3
        anomaly_days = daily_df[daily_df["total_activity"] > anomaly_threshold]

        result = {
            "daily_avg": float(daily_avg),
            "daily_max": float(daily_max),
            "daily_min": float(daily_min),
            "anomaly_detected": len(anomaly_days) > 0,
            "anomaly_count": len(anomaly_days),
            "anomaly_threshold": float(anomaly_threshold)
        }

        logger.info(f"Trend analysis result: {result}")
        return result


def calculate_cost_for_dataframe(df: pd.DataFrame, model_col: str = 'model_name', region: str = "default") -> pd.DataFrame:
    """DataFrame에 비용 컬럼 추가 (리전별 가격 반영)

    Args:
        df: 비용을 계산할 DataFrame
        model_col: 모델명이 있는 컬럼명
        region: AWS 리전 (예: us-east-1, ap-northeast-2)

    Returns:
        pd.DataFrame: 비용 컬럼이 추가된 DataFrame
    """
    logger.info(f"Calculating cost for DataFrame with {len(df)} rows, region: {region}")

    if df.empty:
        return df

    costs = []
    for _, row in df.iterrows():
        model = row.get(model_col, '')
        input_tokens = int(row.get('total_input_tokens', 0)) if row.get('total_input_tokens') else 0
        output_tokens = int(row.get('total_output_tokens', 0)) if row.get('total_output_tokens') else 0
        cost = get_model_cost(model, input_tokens, output_tokens, region)
        costs.append(cost)

    df['estimated_cost_usd'] = costs
    logger.info(f"Total cost calculated for region {region}: ${sum(costs):.4f}")
    return df


def print_summary(summary: Dict):
    """전체 요약 출력"""
    print("\n" + "="*80)
    print("📊 전체 요약".center(80))
    print("="*80)
    print(f"  총 API 호출:       {summary['total_calls']:>15,}")
    print(f"  총 Input 토큰:     {summary['total_input_tokens']:>15,}")
    print(f"  총 Output 토큰:    {summary['total_output_tokens']:>15,}")
    print(f"  총 비용 (USD):     ${summary['total_cost_usd']:>14.4f}")
    print("="*80 + "\n")


def print_dataframe_table(df: pd.DataFrame, title: str, max_rows: int = 20):
    """DataFrame을 테이블 형식으로 출력"""
    if df.empty:
        print(f"\n{title}: 데이터 없음\n")
        return

    print(f"\n{'='*80}")
    print(f"{title}".center(80))
    print("="*80)

    # pandas 출력 옵션 설정
    pd.set_option('display.max_rows', max_rows)
    pd.set_option('display.max_columns', None)
    pd.set_option('display.width', 1000)
    pd.set_option('display.colheader_justify', 'left')

    print(df.head(max_rows).to_string(index=False))

    if len(df) > max_rows:
        print(f"\n... ({len(df) - max_rows} more rows)")

    print("="*80 + "\n")


def save_to_csv(df: pd.DataFrame, filename: str):
    """CSV로 저장"""
    report_dir = Path(__file__).parent / 'report'
    report_dir.mkdir(exist_ok=True)

    filepath = report_dir / filename
    df.to_csv(filepath, index=False, encoding='utf-8-sig')
    print(f"✅ CSV 저장: {filepath}")


def save_to_json(data: dict, filename: str):
    """JSON으로 저장"""
    report_dir = Path(__file__).parent / 'report'
    report_dir.mkdir(exist_ok=True)

    filepath = report_dir / filename
    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    print(f"✅ JSON 저장: {filepath}")


def print_qcli_summary(summary: Dict, token_estimates: Dict, limit_check: Dict = None, trends: Dict = None):
    """QCli 전체 요약 출력"""
    print("\n" + "="*80)
    print("📊 Amazon Q CLI 전체 요약".center(80))
    print("="*80)
    print(f"  활성 사용자:           {summary['unique_users']:>15,}")
    print(f"  활동 일수:             {summary['active_days']:>15,}")
    print(f"  채팅 메시지:           {summary['total_chat_messages']:>15,}")
    print(f"  인라인 제안:           {summary['total_inline_suggestions']:>15,}")
    print(f"  인라인 수락:           {summary['total_inline_acceptances']:>15,}")
    print(f"  채팅 코드 라인:        {summary['total_chat_code_lines']:>15,}")
    print(f"  인라인 코드 라인:      {summary['total_inline_code_lines']:>15,}")
    print(f"  /dev 이벤트:           {summary['total_dev_events']:>15,}")
    print(f"  /test 이벤트:          {summary['total_test_events']:>15,}")
    print("="*80 + "\n")

    # 토큰 추정치 출력 (평균만)
    print("\n" + "="*80)
    print("🔢 토큰 사용량 추정 (참고용)".center(80))
    print("="*80)
    print("💡 참고: Amazon Q Developer Pro는 $19/월 정액제입니다.")
    print("   아래 토큰 추정치는 실제 청구 비용과 무관하며 ROI 분석 용도입니다.\n")

    # 평균 추정치만 사용
    token_avg = token_estimates.get("average", token_estimates[list(token_estimates.keys())[0]])

    print(f"  Input 토큰:       {token_avg['estimated_input_tokens']:>15,}")
    print(f"  Output 토큰:      {token_avg['estimated_output_tokens']:>15,}")
    print(f"  총 토큰:          {token_avg['estimated_total_tokens']:>15,}")

    # 가상 비용 계산 (Claude Sonnet 3.5 가격 기준)
    MODEL_PRICING = {
        "input": 0.003 / 1000,
        "output": 0.015 / 1000,
    }
    virtual_cost = (
        token_avg['estimated_input_tokens'] * MODEL_PRICING['input'] +
        token_avg['estimated_output_tokens'] * MODEL_PRICING['output']
    )
    print(f"  가상 비용:        ${virtual_cost:>14.2f}")
    print()

    # ROI 비교
    print("💰 ROI 분석:")
    subscription_cost = 19.0
    days_in_period = (summary.get('active_days', 30))
    prorated_subscription = subscription_cost * (days_in_period / 30)

    print(f"  구독료 (일할):    ${prorated_subscription:>14.2f}")
    print(f"  가상 사용 비용:   ${virtual_cost:>14.2f}")

    savings = virtual_cost - prorated_subscription
    if savings > 0:
        savings_pct = (savings / virtual_cost) * 100
        print(f"  절감액:           ${savings:>14.2f} ({savings_pct:.1f}% 절감)")
    else:
        loss_pct = (-savings / prorated_subscription) * 100
        print(f"  손실:             ${-savings:>14.2f} ({loss_pct:.1f}% 손실)")

    print("="*80 + "\n")

    # 리밋 체크 출력
    if limit_check:
        print("\n" + "="*80)
        print("⚠️ 공식 리밋 모니터링".center(80))
        print("="*80)

        dev_limit = limit_check["dev_events"]
        trans_limit = limit_check["transformation_lines"]

        print("\n🔧 /dev 명령어:")
        print(f"   현재 사용량:  {dev_limit['used']:>3} / {dev_limit['limit']:>3}회")
        print(f"   월간 예상:    {dev_limit['projected_monthly']:>3}회 ({dev_limit['percentage']:.1f}%)")
        if dev_limit['warning']:
            print(f"   ⚠️  경고: 월간 리밋의 {dev_limit['percentage']:.1f}% 도달!")
        elif dev_limit['percentage'] > 50:
            print(f"   ⚠️  주의: 월간 리밋의 {dev_limit['percentage']:.1f}%")
        else:
            print(f"   ✅ 정상: 월간 리밋의 {dev_limit['percentage']:.1f}%")

        print("\n🔄 Code Transformation:")
        print(f"   현재 사용량:  {trans_limit['used']:>5,} / {trans_limit['limit']:>5,}줄")
        print(f"   월간 예상:    {trans_limit['projected_monthly']:>5,}줄 ({trans_limit['percentage']:.1f}%)")
        if trans_limit['warning']:
            print(f"   ⚠️  경고: 월간 리밋의 {trans_limit['percentage']:.1f}% 도달!")
        elif trans_limit['percentage'] > 50:
            print(f"   ⚠️  주의: 월간 리밋의 {trans_limit['percentage']:.1f}%")
        else:
            print(f"   ✅ 정상: 월간 리밋의 {trans_limit['percentage']:.1f}%")

        print("\n💡 참고:")
        print("   - 채팅/인라인 제안: AWS가 공식 리밋을 공개하지 않음 (추적 불가)")
        print("   - 실제 리밋 도달 시 AWS 콘솔에서 'Monthly limit reached' 메시지 표시")
        print("="*80 + "\n")

    # 추세 분석 출력
    if trends:
        print("\n" + "="*80)
        print("📈 사용 패턴 분석".center(80))
        print("="*80)
        print(f"  일일 평균 활동:  {trends['daily_avg']:>10.1f}건")
        print(f"  최대 활동일:     {trends['daily_max']:>10.0f}건")
        print(f"  최소 활동일:     {trends['daily_min']:>10.0f}건")

        if trends["anomaly_detected"]:
            print(f"\n  🚨 사용량 급증 감지: {trends['anomaly_count']}일 동안 일평균({trends['daily_avg']:.1f})의")
            print(f"     3배({trends['anomaly_threshold']:.1f})를 초과했습니다!")
            print(f"     리밋 도달 가능성이 높습니다!")
        else:
            print(f"\n  ✅ 정상 패턴: 이상 활동 없음")

        print("="*80 + "\n")


def print_s3_log_summary(stats: Dict):
    """S3 로그 분석 결과 요약 출력"""
    print("\n" + "="*80)
    print("📊 Amazon Q Developer S3 로그 분석 결과".center(80))
    print("="*80)

    # 기본 통계
    print("\n📋 기본 통계:")
    print(f"  분석 기간:        {stats['period']['days']}일")
    print(f"  총 로그 파일:     {stats['total_log_files']:>15,}")
    print(f"  총 요청 수:       {stats['total_requests']:>15,}")
    print(f"  Chat 요청:        {stats['by_type']['chat']['count']:>15,} ({stats['by_type']['chat']['count']/stats['total_requests']*100 if stats['total_requests'] > 0 else 0:.1f}%)")
    print(f"  Inline 제안:      {stats['by_type']['inline']['count']:>15,} ({stats['by_type']['inline']['count']/stats['total_requests']*100 if stats['total_requests'] > 0 else 0:.1f}%)")

    # 토큰 사용량
    print("\n🔢 실제 토큰 사용량:")
    print(f"  Input 토큰:       {stats['total_input_tokens']:>15,}")
    print(f"  Output 토큰:      {stats['total_output_tokens']:>15,}")
    print(f"  총 토큰:          {stats['total_tokens']:>15,}")

    # Context Window 분석
    context_window = 200000
    usage_rate = (stats['total_tokens'] / context_window) * 100
    days_in_period = stats['period']['days']
    daily_avg = stats['total_tokens'] / days_in_period if days_in_period > 0 else 0
    daily_usage_rate = (daily_avg / context_window) * 100

    print("\n📈 Context Window 분석:")
    print(f"  Context Window:   {context_window:>15,} 토큰/세션")
    print(f"  누적 사용률:      {usage_rate:>14.2f}% ({stats['total_tokens']:,} 토큰)")
    print(f"  일일 평균 토큰:   {daily_avg:>15,.0f}")
    print(f"  일일 사용률:      {daily_usage_rate:>14.2f}%")
    print("\n  💡 Context Window는 세션별로 독립 관리되므로,")
    print("     누적 사용률보다 세션당 사용률이 중요합니다.")

    # 타입별 상세 분석
    print("\n📊 타입별 상세 분석:")

    # Chat
    chat_stats = stats['by_type']['chat']
    if chat_stats['count'] > 0:
        chat_avg_input = chat_stats['input_tokens'] / chat_stats['count']
        chat_avg_output = chat_stats['output_tokens'] / chat_stats['count']
        chat_avg_total = (chat_stats['input_tokens'] + chat_stats['output_tokens']) / chat_stats['count']

        print(f"\n  💬 Chat (대화):")
        print(f"     요청 수:       {chat_stats['count']:>10,}")
        print(f"     평균 입력:     {chat_avg_input:>10,.0f} 토큰")
        print(f"     평균 출력:     {chat_avg_output:>10,.0f} 토큰")
        print(f"     평균 총합:     {chat_avg_total:>10,.0f} 토큰")

    # Inline
    inline_stats = stats['by_type']['inline']
    if inline_stats['count'] > 0:
        inline_avg_input = inline_stats['input_tokens'] / inline_stats['count']

        print(f"\n  ⚡ Inline 제안:")
        print(f"     요청 수:       {inline_stats['count']:>10,}")
        print(f"     평균 컨텍스트: {inline_avg_input:>10,.0f} 토큰")
        if inline_stats['output_tokens'] == 0:
            print(f"     평균 출력:     로그에 없음")
        else:
            inline_avg_output = inline_stats['output_tokens'] / inline_stats['count']
            print(f"     평균 출력:     {inline_avg_output:>10,.0f} 토큰")

    # 가상 비용 계산
    print("\n💰 가상 비용 분석 (참고용):")
    print("   💡 Amazon Q Developer Pro는 $19/월 정액제입니다.")
    print("      아래 비용은 Claude API를 직접 사용했을 경우 가정입니다.\n")

    MODEL_PRICING = {
        "input": 0.003 / 1000,
        "output": 0.015 / 1000,
    }

    virtual_cost = (
        stats['total_input_tokens'] * MODEL_PRICING['input'] +
        stats['total_output_tokens'] * MODEL_PRICING['output']
    )

    print(f"  Input 비용:       ${stats['total_input_tokens'] * MODEL_PRICING['input']:>14.2f}")
    print(f"  Output 비용:      ${stats['total_output_tokens'] * MODEL_PRICING['output']:>14.2f}")
    print(f"  총 가상 비용:     ${virtual_cost:>14.2f}")

    # ROI 비교
    subscription_cost = 19.0
    prorated_subscription = subscription_cost * (days_in_period / 30)

    print(f"\n  구독료 (일할):    ${prorated_subscription:>14.2f}")
    print(f"  가상 사용 비용:   ${virtual_cost:>14.2f}")

    savings = virtual_cost - prorated_subscription
    if savings > 0:
        savings_pct = (savings / virtual_cost) * 100
        print(f"  절감액:           ${savings:>14.2f} ({savings_pct:.1f}% 절감)")
    else:
        loss_pct = (-savings / prorated_subscription) * 100 if prorated_subscription > 0 else 0
        print(f"  손실:             ${-savings:>14.2f} ({loss_pct:.1f}% 손실)")

    # 사용자 정보
    if stats['by_user']:
        print(f"\n👥 사용자 분석:")
        print(f"  분석된 사용자:    {len(stats['by_user']):>15,}명")

        # 상위 3명 표시
        sorted_users = sorted(
            stats['by_user'].items(),
            key=lambda x: x[1]['input_tokens'] + x[1]['output_tokens'],
            reverse=True
        )

        if len(sorted_users) > 0:
            print(f"\n  상위 사용자 (토큰 기준):")
            for i, (user_id, user_stats) in enumerate(sorted_users[:3], 1):
                total_tokens = user_stats['input_tokens'] + user_stats['output_tokens']
                print(f"    {i}. {user_id[:40]}...")
                print(f"       요청: {user_stats['requests']:,}, 토큰: {total_tokens:,}")

    print("="*80 + "\n")


def main():
    parser = argparse.ArgumentParser(description='AWS Analytics CLI - Athena 기반 (Bedrock & Amazon Q CLI)')
    parser.add_argument('--service',
                       choices=['bedrock', 'qcli'],
                       default='bedrock',
                       help='분석할 서비스 (기본값: bedrock)')
    parser.add_argument('--days', type=int, default=7, help='분석할 일수 (기본값: 7일)')
    parser.add_argument('--region', default='us-east-1',
                       choices=list(REGIONS.keys()),
                       help='AWS 리전 (기본값: us-east-1)')
    parser.add_argument('--start-date', help='시작 날짜 (YYYY-MM-DD)')
    parser.add_argument('--end-date', help='종료 날짜 (YYYY-MM-DD)')
    parser.add_argument('--analysis',
                       choices=['all', 'summary', 'user', 'user-app', 'model', 'daily', 'hourly', 'feature'],
                       default='all',
                       help='분석 유형 (기본값: all)')
    parser.add_argument('--format',
                       choices=['terminal', 'csv', 'json'],
                       default='terminal',
                       help='출력 형식 (기본값: terminal)')
    parser.add_argument('--max-rows', type=int, default=20,
                       help='테이블 최대 행 수 (기본값: 20)')
    parser.add_argument('--arn-pattern', type=str, default='',
                       help='ARN 패턴 필터 (Bedrock용, 예: AmazonQ-CLI, q-cli)')
    parser.add_argument('--user-pattern', type=str, default='',
                       help='사용자 ID 패턴 필터 (QCli용, 예: user@example.com)')
    parser.add_argument('--data-source',
                       choices=['s3', 'athena'],
                       default='s3',
                       help='QCli 데이터 소스 (s3: 실제 토큰, athena: 추정, 기본값: s3)')

    args = parser.parse_args()

    if args.service == 'bedrock':
        print("🚀 Bedrock Analytics CLI (Athena 기반)")
    else:
        data_source_desc = "S3 로그 (실제 토큰)" if args.data_source == 's3' else "Athena CSV (추정)"
        print(f"🚀 Amazon Q CLI Analytics ({data_source_desc})")
    print("="*80)

    # 날짜 범위 설정
    if args.start_date and args.end_date:
        start_date = datetime.strptime(args.start_date, '%Y-%m-%d')
        end_date = datetime.strptime(args.end_date, '%Y-%m-%d')
    else:
        end_date = datetime.now()
        start_date = end_date - timedelta(days=args.days)

    print(f"📅 분석 기간: {start_date.strftime('%Y-%m-%d')} ~ {end_date.strftime('%Y-%m-%d')}")
    print(f"🌍 리전: {args.region} ({REGIONS[args.region]})")
    print(f"📋 분석 유형: {args.analysis}")
    print(f"📄 출력 형식: {args.format}")

    # 서비스별 필터 설정
    if args.service == 'bedrock':
        arn_pattern = args.arn_pattern if args.arn_pattern else None
        if arn_pattern:
            print(f"🔍 ARN 패턴 필터: '{arn_pattern}'")
    else:
        user_pattern = args.user_pattern if args.user_pattern else None
        if user_pattern:
            print(f"🔍 사용자 ID 패턴 필터: '{user_pattern}'")
    print()

    # 서비스별 분기 처리
    if args.service == 'bedrock':
        # Bedrock 분석
        analyze_bedrock(args, start_date, end_date, arn_pattern if args.arn_pattern else None)
    else:
        # QCli 분석
        analyze_qcli(args, start_date, end_date, user_pattern if args.user_pattern else None)

    print("\n✅ 분석 완료!")
    logger.info("Analysis completed successfully")


def analyze_bedrock(args, start_date: datetime, end_date: datetime, arn_pattern: str = None):
    """Bedrock 분석 실행"""
    # Tracker 초기화
    tracker = BedrockAthenaTracker(region=args.region)

    # 로깅 설정 확인
    print("🔍 Model Invocation Logging 설정 확인 중...")
    current_config = tracker.get_current_logging_config()

    if current_config['status'] == 'enabled':
        print("✅ Model Invocation Logging이 활성화되어 있습니다!")
        print(f"   S3 버킷: {current_config['bucket']}")
        print(f"   프리픽스: {current_config['prefix']}")
    elif current_config['status'] == 'disabled':
        print("❌ Model Invocation Logging이 비활성화되어 있습니다.")
        print("💡 먼저 설정을 활성화해주세요:")
        print("   python setup_bedrock_logging.py")
        return
    else:
        print(f"⚠️ 설정 확인 중 오류: {current_config.get('error', 'Unknown error')}")
        return

    print()
    print("📊 데이터 분석 중...\n")

    # 데이터 수집
    results = {}

    if args.analysis in ['all', 'summary']:
        summary = tracker.get_total_summary(start_date, end_date, arn_pattern)
        results['summary'] = summary

    if args.analysis in ['all', 'user']:
        user_df = tracker.get_user_cost_analysis(start_date, end_date, arn_pattern)
        if not user_df.empty:
            # 숫자 변환 및 비용 계산
            for col in ['call_count', 'total_input_tokens', 'total_output_tokens']:
                if col in user_df.columns:
                    user_df[col] = pd.to_numeric(user_df[col], errors='coerce').fillna(0)
            # 리전별 가격으로 비용 계산 (사용자별 분석은 모델 정보가 없으므로 기본 Haiku 가격 사용)
            costs = []
            for _, row in user_df.iterrows():
                input_tokens = int(row.get('total_input_tokens', 0)) if row.get('total_input_tokens') else 0
                output_tokens = int(row.get('total_output_tokens', 0)) if row.get('total_output_tokens') else 0
                # Claude 3 Haiku를 기본 모델로 사용
                cost = get_model_cost('claude-3-haiku-20240307', input_tokens, output_tokens, args.region)
                costs.append(cost)
            user_df['estimated_cost_usd'] = costs
        results['user'] = user_df

    if args.analysis in ['all', 'user-app']:
        user_app_df = tracker.get_user_app_detail_analysis(start_date, end_date, arn_pattern)
        if not user_app_df.empty:
            for col in ['call_count', 'total_input_tokens', 'total_output_tokens']:
                if col in user_app_df.columns:
                    user_app_df[col] = pd.to_numeric(user_app_df[col], errors='coerce').fillna(0)
            user_app_df = calculate_cost_for_dataframe(user_app_df, region=args.region)
        results['user_app'] = user_app_df

    if args.analysis in ['all', 'model']:
        model_df = tracker.get_model_usage_stats(start_date, end_date, arn_pattern)
        if not model_df.empty:
            for col in ['call_count', 'avg_input_tokens', 'avg_output_tokens',
                       'total_input_tokens', 'total_output_tokens']:
                if col in model_df.columns:
                    model_df[col] = pd.to_numeric(model_df[col], errors='coerce').fillna(0)
            model_df = calculate_cost_for_dataframe(model_df, region=args.region)
            # 총 비용 업데이트
            if 'summary' in results:
                results['summary']['total_cost_usd'] = model_df['estimated_cost_usd'].sum()
        results['model'] = model_df

    if args.analysis in ['all', 'daily']:
        daily_df = tracker.get_daily_usage_pattern(start_date, end_date, arn_pattern)
        if not daily_df.empty:
            for col in ['call_count', 'total_input_tokens', 'total_output_tokens']:
                if col in daily_df.columns:
                    daily_df[col] = pd.to_numeric(daily_df[col], errors='coerce').fillna(0)
        results['daily'] = daily_df

    if args.analysis in ['all', 'hourly']:
        hourly_df = tracker.get_hourly_usage_pattern(start_date, end_date, arn_pattern)
        if not hourly_df.empty:
            for col in ['call_count', 'total_input_tokens', 'total_output_tokens']:
                if col in hourly_df.columns:
                    hourly_df[col] = pd.to_numeric(hourly_df[col], errors='coerce').fillna(0)
        results['hourly'] = hourly_df

    # 출력 형식에 따라 결과 출력
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')

    if args.format == 'terminal':
        # 터미널 출력
        if 'summary' in results:
            print_summary(results['summary'])

        if 'user' in results and not results['user'].empty:
            print_dataframe_table(results['user'], "👥 사용자/애플리케이션별 분석", args.max_rows)

        if 'user_app' in results and not results['user_app'].empty:
            print_dataframe_table(results['user_app'], "📱 유저별 애플리케이션별 상세 분석", args.max_rows)

        if 'model' in results and not results['model'].empty:
            print_dataframe_table(results['model'], "🤖 모델별 사용 통계", args.max_rows)

        if 'daily' in results and not results['daily'].empty:
            print_dataframe_table(results['daily'], "📅 일별 사용 패턴", args.max_rows)

        if 'hourly' in results and not results['hourly'].empty:
            print_dataframe_table(results['hourly'], "⏰ 시간별 사용 패턴", args.max_rows)

    elif args.format == 'csv':
        # CSV 저장
        for key, data in results.items():
            if key == 'summary':
                continue
            if isinstance(data, pd.DataFrame) and not data.empty:
                filename = f"bedrock_{key}_{args.region}_{timestamp}.csv"
                save_to_csv(data, filename)

    elif args.format == 'json':
        # JSON 저장
        json_data = {}

        if 'summary' in results:
            json_data['summary'] = results['summary']

        for key, data in results.items():
            if key == 'summary':
                continue
            if isinstance(data, pd.DataFrame) and not data.empty:
                json_data[key] = data.to_dict(orient='records')

        filename = f"bedrock_analysis_{args.region}_{timestamp}.json"
        save_to_json(json_data, filename)


def analyze_qcli(args, start_date: datetime, end_date: datetime, user_pattern: str = None):
    """QCli 분석 실행"""
    print("📊 Amazon Q CLI 데이터 분석 중...\n")

    # 데이터 소스별로 다른 분석 실행
    if args.data_source == 's3':
        # S3 로그 분석
        try:
            s3_analyzer = QCliS3LogAnalyzer(region=args.region, logger=logger)

            # S3 로그 분석 실행
            stats = s3_analyzer.analyze_usage(start_date, end_date, user_pattern)

            # 결과 출력
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')

            if args.format == 'terminal':
                print_s3_log_summary(stats)
            elif args.format == 'json':
                filename = f"qcli_s3_analysis_{args.region}_{timestamp}.json"
                save_to_json(stats, filename)
            elif args.format == 'csv':
                # S3 데이터를 DataFrame으로 변환하여 CSV 저장
                if stats['by_user']:
                    user_data = []
                    for user_id, user_stats in stats['by_user'].items():
                        user_data.append({
                            '사용자 ID': user_id,
                            '요청 수': user_stats['requests'],
                            'Input 토큰': user_stats['input_tokens'],
                            'Output 토큰': user_stats['output_tokens'],
                            '총 토큰': user_stats['input_tokens'] + user_stats['output_tokens']
                        })
                    user_df = pd.DataFrame(user_data)
                    filename = f"qcli_s3_users_{args.region}_{timestamp}.csv"
                    save_to_csv(user_df, filename)

                if stats['by_date']:
                    date_data = []
                    for date_str, date_stats in stats['by_date'].items():
                        date_data.append({
                            '날짜': date_str,
                            '요청 수': date_stats['requests'],
                            'Input 토큰': date_stats['input_tokens'],
                            'Output 토큰': date_stats['output_tokens'],
                            '총 토큰': date_stats['input_tokens'] + date_stats['output_tokens']
                        })
                    date_df = pd.DataFrame(date_data)
                    filename = f"qcli_s3_daily_{args.region}_{timestamp}.csv"
                    save_to_csv(date_df, filename)

        except Exception as e:
            logger.error(f"S3 로그 분석 중 오류: {e}", exc_info=True)
            print(f"❌ S3 로그 분석 중 오류가 발생했습니다: {e}")
            print("💡 프롬프트 로깅이 활성화되어 있는지, S3 버킷에 로그 파일이 있는지 확인하세요.")
            return

    else:
        # 기존 Athena CSV 분석
        tracker = QCliAthenaTracker(region=args.region)

        # 데이터 수집
        results = {}

        if args.analysis in ['all', 'summary']:
            summary = tracker.get_total_summary(start_date, end_date, user_pattern)
            results['summary'] = summary

            # 토큰 추정
            token_conservative = tracker.estimate_tokens(summary, "conservative")
            token_average = tracker.estimate_tokens(summary, "average")
            token_optimistic = tracker.estimate_tokens(summary, "optimistic")

            results['token_estimates'] = {
                "conservative": token_conservative,
                "average": token_average,
                "optimistic": token_optimistic
            }

            # 리밋 체크 및 추세 분석 추가
            days_in_period = (end_date - start_date).days + 1
            results['limit_check'] = tracker.check_official_limits(summary, days_in_period)
            results['trends'] = tracker.analyze_usage_trends(start_date, end_date, user_pattern)

        if args.analysis in ['all', 'user']:
            user_df = tracker.get_user_usage_analysis(start_date, end_date, user_pattern)
            if not user_df.empty:
                numeric_columns = [
                    "total_chat_messages",
                    "total_inline_suggestions",
                    "total_inline_acceptances",
                    "total_chat_code_lines",
                    "total_inline_code_lines",
                    "total_dev_events",
                    "total_test_events",
                    "total_doc_events",
                    "active_days",
                ]
                for col in numeric_columns:
                    if col in user_df.columns:
                        user_df[col] = pd.to_numeric(user_df[col], errors='coerce').fillna(0)
            results['user'] = user_df

        if args.analysis in ['all', 'feature']:
            feature_df = tracker.get_feature_usage_stats(start_date, end_date, user_pattern)
            if not feature_df.empty:
                for col in ["total_count", "unique_users"]:
                    if col in feature_df.columns:
                        feature_df[col] = pd.to_numeric(feature_df[col], errors='coerce').fillna(0)
            results['feature'] = feature_df

        if args.analysis in ['all', 'daily']:
            daily_df = tracker.get_daily_usage_pattern(start_date, end_date, user_pattern)
            if not daily_df.empty:
                numeric_columns = [
                    "total_chat_messages",
                    "total_inline_suggestions",
                    "total_inline_acceptances",
                    "total_chat_code_lines",
                    "total_inline_code_lines",
                    "unique_users",
                ]
                for col in numeric_columns:
                    if col in daily_df.columns:
                        daily_df[col] = pd.to_numeric(daily_df[col], errors='coerce').fillna(0)
            results['daily'] = daily_df

        # 출력 형식에 따라 결과 출력
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')

        if args.format == 'terminal':
            # 터미널 출력
            if 'summary' in results and 'token_estimates' in results:
                print_qcli_summary(
                    results['summary'],
                    results['token_estimates'],
                    results.get('limit_check'),
                    results.get('trends')
                )

            if 'user' in results and not results['user'].empty:
                print_dataframe_table(results['user'], "👥 사용자별 분석", args.max_rows)

            if 'feature' in results and not results['feature'].empty:
                print_dataframe_table(results['feature'], "📱 기능별 사용 통계", args.max_rows)

            if 'daily' in results and not results['daily'].empty:
                print_dataframe_table(results['daily'], "📅 일별 사용 패턴", args.max_rows)

        elif args.format == 'csv':
            # CSV 저장
            for key, data in results.items():
                if key in ['summary', 'token_estimates']:
                    continue
                if isinstance(data, pd.DataFrame) and not data.empty:
                    filename = f"qcli_{key}_{args.region}_{timestamp}.csv"
                    save_to_csv(data, filename)

        elif args.format == 'json':
            # JSON 저장
            json_data = {}

            if 'summary' in results:
                json_data['summary'] = results['summary']

            if 'token_estimates' in results:
                json_data['token_estimates'] = results['token_estimates']

            for key, data in results.items():
                if key in ['summary', 'token_estimates']:
                    continue
                if isinstance(data, pd.DataFrame) and not data.empty:
                    json_data[key] = data.to_dict(orient='records')

            filename = f"qcli_analysis_{args.region}_{timestamp}.json"
            save_to_json(json_data, filename)


if __name__ == "__main__":
    main()

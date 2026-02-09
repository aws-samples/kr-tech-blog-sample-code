import streamlit as st
import boto3
import pandas as pd
from datetime import datetime, timedelta
import time
from typing import Dict, List
import logging
import os
from pathlib import Path

# Amazon Q Developer S3 로그 분석 모듈
from qcli_s3_analyzer import QCliS3LogAnalyzer


# 로깅 설정
def setup_logger():
    """디버깅용 로거 설정"""
    log_dir = Path(__file__).parent / "log"
    log_dir.mkdir(exist_ok=True)

    log_filename = (
        log_dir / f"bedrock_tracker_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
    )

    logger = logging.getLogger("BedrockTracker")
    logger.setLevel(logging.DEBUG)

    # 파일 핸들러
    file_handler = logging.FileHandler(log_filename, encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)

    # 포맷 설정
    formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(funcName)s:%(lineno)d - %(message)s"
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

default_region = "us-east-1"


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
    model_name = model_id.split(".")[-1].split("-v")[0] if "." in model_id else model_id

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
    def __init__(self, region=default_region):
        logger.info(f"Initializing BedrockAthenaTracker with region: {region}")
        self.region = region
        self.athena = boto3.client("athena", region_name=region)
        # STS 클라이언트도 region을 지정하여 생성
        sts_client = boto3.client("sts", region_name=region)
        self.account_id = sts_client.get_caller_identity()["Account"]
        # 리전별 Athena 결과 저장용 버킷
        self.results_bucket = f"bedrock-analytics-{self.account_id}-{self.region}"
        logger.info(
            f"Account ID: {self.account_id}, Results bucket: {self.results_bucket}"
        )

    def get_current_logging_config(self) -> Dict:
        """현재 설정된 Model Invocation Logging 정보 조회"""
        logger.info("Getting current logging configuration")
        try:
            bedrock = boto3.client("bedrock", region_name=self.region)
            response = bedrock.get_model_invocation_logging_configuration()

            if "loggingConfig" in response:
                config = response["loggingConfig"]

                if "s3Config" in config:
                    result = {
                        "type": "s3",
                        "bucket": config["s3Config"].get("bucketName", ""),
                        "prefix": config["s3Config"].get("keyPrefix", ""),
                        "status": "enabled",
                    }
                    logger.info(f"Logging config: {result}")
                    return result

            logger.warning("Logging is disabled")
            return {"status": "disabled"}

        except Exception as e:
            logger.error(f"Error getting logging config: {str(e)}")
            return {"status": "error", "error": str(e)}

    def set_results_bucket(self, bucket_name: str):
        """Athena 결과 저장용 버킷 설정"""
        self.results_bucket = bucket_name
        logger.info(f"Results bucket set to: {self.results_bucket}")

    def execute_athena_query(
        self, query: str, database: str = "bedrock_analytics"
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
            st.error(f"Athena 쿼리 실행 실패: {str(e)}")
            return pd.DataFrame()

    def get_user_cost_analysis(
        self, start_date: datetime, end_date: datetime, arn_pattern: str = None
    ) -> pd.DataFrame:
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

    def get_user_app_detail_analysis(
        self, start_date: datetime, end_date: datetime, arn_pattern: str = None
    ) -> pd.DataFrame:
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

    def get_hourly_usage_pattern(
        self, start_date: datetime, end_date: datetime, arn_pattern: str = None
    ) -> pd.DataFrame:
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

    def get_daily_usage_pattern(
        self, start_date: datetime, end_date: datetime, arn_pattern: str = None
    ) -> pd.DataFrame:
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

    def get_model_usage_stats(
        self, start_date: datetime, end_date: datetime, arn_pattern: str = None
    ) -> pd.DataFrame:
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
                "total_calls": (
                    int(df.iloc[0]["total_calls"]) if df.iloc[0]["total_calls"] else 0
                ),
                "total_input_tokens": (
                    int(df.iloc[0]["total_input_tokens"])
                    if df.iloc[0]["total_input_tokens"]
                    else 0
                ),
                "total_output_tokens": (
                    int(df.iloc[0]["total_output_tokens"])
                    if df.iloc[0]["total_output_tokens"]
                    else 0
                ),
                "total_cost_usd": 0.0,  # 모델별로 계산 필요
            }
            logger.info(f"Total summary: {result}")
            return result
        else:
            logger.warning("No data found for summary")
            return {
                "total_calls": 0,
                "total_input_tokens": 0,
                "total_output_tokens": 0,
                "total_cost_usd": 0.0,
            }


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

    def __init__(self, region=default_region):
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
            st.error(f"Athena 쿼리 실행 실패: {str(e)}")
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


def calculate_cost_for_dataframe(
    df: pd.DataFrame, model_col: str = "model_name", region: str = "default"
) -> pd.DataFrame:
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
        model = row.get(model_col, "")
        input_tokens = (
            int(row.get("total_input_tokens", 0))
            if row.get("total_input_tokens")
            else 0
        )
        output_tokens = (
            int(row.get("total_output_tokens", 0))
            if row.get("total_output_tokens")
            else 0
        )
        cost = get_model_cost(model, input_tokens, output_tokens, region)
        costs.append(cost)

    df["estimated_cost_usd"] = costs
    logger.info(f"Total cost calculated for region {region}: ${sum(costs):.4f}")
    return df


def main():
    logger.info("Starting Analytics Dashboard")

    st.set_page_config(
        page_title="AWS Analytics Dashboard", page_icon="📊", layout="wide"
    )

    st.title("📊 AWS Analytics Dashboard")
    st.markdown("**Athena 기반 실시간 사용량 분석 - Bedrock & Amazon Q CLI**")

    # 사이드바 설정
    st.sidebar.header("⚙️ 분석 설정")

    # 분석 유형 선택
    analysis_type = st.sidebar.radio(
        "분석 유형 선택",
        ["AWS Bedrock", "Amazon Q CLI"],
        index=0
    )

    # 리전 선택
    if analysis_type == "Amazon Q CLI":
        # Amazon Q CLI는 us-east-1에서만 사용자 활동 리포트 관리
        st.sidebar.info("ℹ️ Amazon Q CLI 사용자 활동 리포트는 us-east-1에서만 관리됩니다.")
        selected_region = "us-east-1"
        st.sidebar.text(f"리전: {selected_region} - {REGIONS[selected_region]} (고정)")
    else:
        # Bedrock은 모든 리전 선택 가능
        selected_region = st.sidebar.selectbox(
            "리전 선택",
            options=list(REGIONS.keys()),
            format_func=lambda x: f"{x} - {REGIONS[x]}",
            index=4,
        )

    logger.info(f"Selected region: {selected_region}, Analysis type: {analysis_type}")

    # 날짜 범위 선택
    st.sidebar.subheader("📅 날짜 범위 선택")

    col1, col2 = st.sidebar.columns(2)
    with col1:
        start_date = st.date_input(
            "시작 날짜",
            value=datetime.now() - timedelta(days=7),
            max_value=datetime.now(),
        )
    with col2:
        end_date = st.date_input(
            "종료 날짜", value=datetime.now(), max_value=datetime.now()
        )

    logger.info(f"Date range: {start_date} to {end_date}")

    # 분석 유형에 따라 다른 대시보드 렌더링
    if analysis_type == "AWS Bedrock":
        render_bedrock_analytics(selected_region, start_date, end_date)
    else:
        render_qcli_analytics(selected_region, start_date, end_date)


def render_bedrock_analytics(selected_region, start_date, end_date):
    """Bedrock 분석 대시보드 렌더링"""
    logger.info("Rendering Bedrock Analytics")

    # ARN 패턴 필터
    st.sidebar.subheader("🔍 ARN 패턴 필터 (선택사항)")
    arn_pattern = st.sidebar.text_input(
        "ARN 패턴",
        value="",
        placeholder="예: AmazonQ-CLI, q-cli",
        key="bedrock_arn_pattern",
        help="특정 ARN 패턴을 포함하는 사용자만 필터링합니다. 비워두면 전체 사용자를 표시합니다."
    )

    # 현재 로깅 설정 자동 조회
    tracker = BedrockAthenaTracker(region=selected_region)

    with st.spinner("현재 Model Invocation Logging 설정 확인 중..."):
        current_config = tracker.get_current_logging_config()

    # 설정 상태 표시
    if current_config["status"] == "enabled":
        st.success("✅ Model Invocation Logging이 활성화되어 있습니다!")

        col1, col2 = st.columns(2)
        with col1:
            st.info(f"📁 **S3 버킷**: 설정됨 ({selected_region})")
        with col2:
            st.info(f"📂 **프리픽스**: 설정됨")

    elif current_config["status"] == "disabled":
        st.error("❌ Model Invocation Logging이 비활성화되어 있습니다.")
        st.markdown("👇 먼저 설정을 활성화해주세요:")
        st.code("python setup_bedrock_analytics.py")
        logger.error("Model Invocation Logging is disabled")
        return

    else:
        st.warning(
            f"⚠️ 설정 확인 중 오류: {current_config.get('error', 'Unknown error')}"
        )
        logger.error(f"Error checking logging config: {current_config.get('error')}")
        return

    # 분석 실행
    if st.sidebar.button("🔍 데이터 분석", type="primary"):
        logger.info("Analysis button clicked")

        with st.spinner("Athena에서 데이터 분석 중..."):

            # ARN 패턴 정보 표시
            if arn_pattern:
                st.info(f"🔍 ARN 패턴 필터링 적용: '{arn_pattern}'")

            # 전체 요약
            summary = tracker.get_total_summary(start_date, end_date, arn_pattern if arn_pattern else None)

            st.header("📊 전체 요약")

            col1, col2, col3, col4 = st.columns(4)

            with col1:
                st.metric("총 API 호출", f"{summary['total_calls']:,}")

            with col2:
                st.metric("총 Input 토큰", f"{summary['total_input_tokens']:,}")

            with col3:
                st.metric("총 Output 토큰", f"{summary['total_output_tokens']:,}")

            # 모델별 통계로 총 비용 계산
            model_df = tracker.get_model_usage_stats(start_date, end_date, arn_pattern if arn_pattern else None)
            if not model_df.empty:
                model_df = calculate_cost_for_dataframe(model_df, region=selected_region)
                total_cost = model_df["estimated_cost_usd"].sum()
                summary["total_cost_usd"] = total_cost

            with col4:
                st.metric("총 비용", f"${summary['total_cost_usd']:.4f}")

            # 사용자별 분석
            st.header("👥 사용자/애플리케이션별 분석")

            user_df = tracker.get_user_cost_analysis(start_date, end_date, arn_pattern if arn_pattern else None)

            if not user_df.empty:
                # 숫자 컬럼 변환
                numeric_columns = [
                    "call_count",
                    "total_input_tokens",
                    "total_output_tokens",
                ]
                for col in numeric_columns:
                    if col in user_df.columns:
                        user_df[col] = pd.to_numeric(
                            user_df[col], errors="coerce"
                        ).fillna(0)

                # 비용 계산을 위한 임시 모델명 추가 (모델별 평균 사용)
                # 실제로는 각 사용자가 어떤 모델을 사용했는지 알아야 정확함
                # 여기서는 Claude 3 Haiku 기본 가격 사용 (리전별 가격 반영)
                costs = []
                for _, row in user_df.iterrows():
                    input_tokens = int(row.get("total_input_tokens", 0)) if row.get("total_input_tokens") else 0
                    output_tokens = int(row.get("total_output_tokens", 0)) if row.get("total_output_tokens") else 0
                    # Claude 3 Haiku를 기본 모델로 사용
                    cost = get_model_cost("claude-3-haiku-20240307", input_tokens, output_tokens, selected_region)
                    costs.append(cost)
                user_df["estimated_cost_usd"] = costs

                st.dataframe(user_df, use_container_width=True)

                # 비용 차트
                if len(user_df) > 0:
                    import plotly.express as px

                    fig = px.bar(
                        user_df.head(10),
                        x="user_or_app",
                        y="estimated_cost_usd",
                        title="상위 10명 사용자/애플리케이션별 비용",
                        labels={
                            "user_or_app": "사용자/애플리케이션",
                            "estimated_cost_usd": "비용 (USD)",
                        },
                    )
                    st.plotly_chart(fig, use_container_width=True)
            else:
                st.info("분석할 데이터가 없습니다.")

            # 유저별 애플리케이션별 상세 분석
            st.header("📱 유저별 애플리케이션별 상세 분석")

            user_app_df = tracker.get_user_app_detail_analysis(start_date, end_date, arn_pattern if arn_pattern else None)

            if not user_app_df.empty:
                # 숫자 컬럼 변환
                numeric_columns = [
                    "call_count",
                    "total_input_tokens",
                    "total_output_tokens",
                ]
                for col in numeric_columns:
                    if col in user_app_df.columns:
                        user_app_df[col] = pd.to_numeric(
                            user_app_df[col], errors="coerce"
                        ).fillna(0)

                # 비용 계산 (리전별 가격 반영)
                user_app_df = calculate_cost_for_dataframe(user_app_df, region=selected_region)

                st.dataframe(user_app_df, use_container_width=True)
            else:
                st.info("분석할 데이터가 없습니다.")

            # 모델별 분석
            st.header("🤖 모델별 사용 통계")

            if not model_df.empty:
                # 숫자 컬럼 변환
                numeric_columns = [
                    "call_count",
                    "avg_input_tokens",
                    "avg_output_tokens",
                    "total_input_tokens",
                    "total_output_tokens",
                    "estimated_cost_usd",
                ]
                for col in numeric_columns:
                    if col in model_df.columns:
                        model_df[col] = pd.to_numeric(
                            model_df[col], errors="coerce"
                        ).fillna(0)

                st.dataframe(model_df, use_container_width=True)

                # 모델별 호출 비율 차트
                if len(model_df) > 0:
                    import plotly.express as px

                    fig = px.pie(
                        model_df,
                        values="call_count",
                        names="model_name",
                        title="모델별 호출 비율",
                    )
                    st.plotly_chart(fig, use_container_width=True)

            # 일별 사용 패턴
            st.header("📅 일별 사용 패턴")

            daily_df = tracker.get_daily_usage_pattern(start_date, end_date, arn_pattern if arn_pattern else None)

            if not daily_df.empty and len(daily_df) > 0:
                # 날짜 컬럼 생성 (숫자를 문자열로 변환 후 zfill 적용)
                daily_df["date"] = pd.to_datetime(
                    daily_df["year"].astype(str)
                    + "-"
                    + daily_df["month"].astype(str).str.zfill(2)
                    + "-"
                    + daily_df["day"].astype(str).str.zfill(2)
                )

                # 숫자 컬럼 변환
                numeric_columns = ["call_count", "total_input_tokens", "total_output_tokens"]
                for col in numeric_columns:
                    if col in daily_df.columns:
                        daily_df[col] = pd.to_numeric(
                            daily_df[col], errors="coerce"
                        ).fillna(0)

                # 표시용 DataFrame 생성 (날짜를 문자열로 포맷)
                display_df = daily_df.copy()
                display_df["날짜"] = display_df["date"].dt.strftime("%Y-%m-%d")
                display_df = display_df[["날짜", "call_count", "total_input_tokens", "total_output_tokens"]]
                display_df.columns = ["날짜", "API 호출 수", "Input 토큰", "Output 토큰"]

                # 1. 테이블 먼저 표시
                st.dataframe(display_df, use_container_width=True)

                # 2. 그래프 표시
                import plotly.express as px
                import plotly.graph_objects as go

                # 일별 API 호출 패턴
                fig = px.line(
                    daily_df,
                    x="date",
                    y="call_count",
                    title="일별 API 호출 패턴",
                    labels={"date": "날짜", "call_count": "API 호출 수"},
                    markers=True
                )
                st.plotly_chart(fig, use_container_width=True)

                # 일별 토큰 사용량
                fig2 = go.Figure()
                fig2.add_trace(go.Scatter(
                    x=daily_df["date"],
                    y=daily_df["total_input_tokens"],
                    mode='lines+markers',
                    name='Input 토큰',
                    line=dict(color='blue')
                ))
                fig2.add_trace(go.Scatter(
                    x=daily_df["date"],
                    y=daily_df["total_output_tokens"],
                    mode='lines+markers',
                    name='Output 토큰',
                    line=dict(color='red')
                ))
                fig2.update_layout(
                    title="일별 토큰 사용량",
                    xaxis_title="날짜",
                    yaxis_title="토큰 수",
                    hovermode='x unified'
                )
                st.plotly_chart(fig2, use_container_width=True)
            else:
                st.warning("선택한 기간에 일별 사용 데이터가 없습니다.")

            # 시간대별 패턴
            st.header("⏰ 시간대별 사용 패턴")

            hourly_df = tracker.get_hourly_usage_pattern(start_date, end_date, arn_pattern if arn_pattern else None)

            if not hourly_df.empty and len(hourly_df) > 0:
                # 시간 컬럼 생성 (숫자를 문자열로 변환 후 zfill 적용)
                hourly_df["datetime"] = pd.to_datetime(
                    hourly_df["year"].astype(str)
                    + "-"
                    + hourly_df["month"].astype(str).str.zfill(2)
                    + "-"
                    + hourly_df["day"].astype(str).str.zfill(2)
                    + " "
                    + hourly_df["hour"].astype(str).str.zfill(2)
                    + ":00:00"
                )

                # 숫자 컬럼 변환
                numeric_columns = ["call_count", "total_input_tokens", "total_output_tokens"]
                for col in numeric_columns:
                    if col in hourly_df.columns:
                        hourly_df[col] = pd.to_numeric(
                            hourly_df[col], errors="coerce"
                        ).fillna(0)

                # 표시용 DataFrame 생성
                display_df = hourly_df.copy()
                display_df["시간"] = display_df["datetime"].dt.strftime("%Y-%m-%d %H:00")
                display_df = display_df[["시간", "call_count", "total_input_tokens", "total_output_tokens"]]
                display_df.columns = ["시간", "API 호출 수", "Input 토큰", "Output 토큰"]

                # 1. 테이블 먼저 표시
                st.dataframe(display_df, use_container_width=True)

                # 2. 그래프 표시
                import plotly.express as px
                import plotly.graph_objects as go

                # 시간대별 API 호출 패턴
                fig = px.line(
                    hourly_df,
                    x="datetime",
                    y="call_count",
                    title="시간대별 API 호출 패턴",
                    labels={"datetime": "시간", "call_count": "API 호출 수"},
                    markers=True
                )
                st.plotly_chart(fig, use_container_width=True)

                # 시간대별 토큰 사용량
                fig2 = go.Figure()
                fig2.add_trace(go.Scatter(
                    x=hourly_df["datetime"],
                    y=hourly_df["total_input_tokens"],
                    mode='lines+markers',
                    name='Input 토큰',
                    line=dict(color='blue')
                ))
                fig2.add_trace(go.Scatter(
                    x=hourly_df["datetime"],
                    y=hourly_df["total_output_tokens"],
                    mode='lines+markers',
                    name='Output 토큰',
                    line=dict(color='red')
                ))
                fig2.update_layout(
                    title="시간대별 토큰 사용량",
                    xaxis_title="시간",
                    yaxis_title="토큰 수",
                    hovermode='x unified'
                )
                st.plotly_chart(fig2, use_container_width=True)
            else:
                st.warning("선택한 기간에 시간대별 사용 데이터가 없습니다.")

    else:
        # 초기 화면
        st.info(
            "👈 왼쪽 사이드바에서 리전과 날짜 범위를 선택한 후 '데이터 분석' 버튼을 클릭하세요."
        )

        st.markdown("### 🛠️ 환경 설정 가이드")

        st.markdown("#### 1️⃣ 환경 요구사항")
        st.markdown(
            """
        **AWS 권한**: 다음 서비스에 대한 권한이 필요합니다
        - Bedrock: InvokeModel, Get/PutModelInvocationLoggingConfiguration
        - S3: GetObject, ListBucket, PutObject, CreateBucket
        - Athena: StartQueryExecution, GetQueryExecution, GetQueryResults
        - Glue: CreateDatabase, CreateTable, GetDatabase, GetTable

        **Python 환경**:
        - Python 3.8 이상
        - boto3, streamlit, pandas, plotly
        """
        )

        st.markdown("#### 2️⃣ 설치 방법")
        st.code(
            """
# 1. 패키지 설치
pip install -r requirements.txt

# 2. AWS 자격증명 설정
aws configure
# 또는 환경변수 설정
export AWS_ACCESS_KEY_ID=your_key
export AWS_SECRET_ACCESS_KEY=your_secret
export AWS_DEFAULT_REGION=us-east-1
        """,
            language="bash"
        )

        st.markdown("#### 3️⃣ 초기 설정 단계")
        st.code(
            """
# Step 1: Athena 분석 환경 구축
python setup_athena_bucket.py

# Step 2: Bedrock 로깅 설정 확인 및 활성화
python check_bedrock_logging.py
python setup_bedrock_logging.py

# Step 3: IAM Role 권한 검증
python verify_bedrock_permissions.py

# Step 4: 테스트 데이터 생성 (선택사항)
python generate_test_data.py

# Step 5: 대시보드 실행
streamlit run bedrock_tracker.py
        """,
            language="bash"
        )

        st.markdown("### 📋 지원 모델")
        st.markdown(
            """
        - **Claude 3**: Haiku, Sonnet, Opus
        - **Claude 3.5**: Haiku, Sonnet
        - **Claude 3.7**: Sonnet
        - **Claude 4**: Sonnet 4, Sonnet 4.5
        - **Claude 4.1**: Opus
        """
        )

        st.markdown("### 🌍 지원 리전")
        for region_id, region_name in REGIONS.items():
            st.markdown(f"- **{region_id}**: {region_name}")

    logger.info("Bedrock Dashboard rendering complete")


def render_qcli_analytics(selected_region, start_date, end_date):
    """Amazon Q CLI 분석 대시보드 렌더링"""
    logger.info("Rendering Amazon Q CLI Analytics")

    # 데이터 소스 선택
    st.sidebar.subheader("📊 데이터 소스 선택")
    data_source = st.sidebar.radio(
        "분석 데이터 소스",
        options=["S3 로그 (실제 토큰)", "Athena CSV (추정)"],
        index=0,
        key="qcli_data_source",
        help="S3 로그: 실제 프롬프트 로그에서 토큰 계산 (정확)\nAthena CSV: 사용자 활동 리포트에서 토큰 추정 (빠름)"
    )

    # 사용자 패턴 필터
    st.sidebar.subheader("🔍 사용자 ID 필터 (선택사항)")
    user_pattern = st.sidebar.text_input(
        "사용자 ID 패턴",
        value="",
        placeholder="예: user@example.com",
        key="qcli_user_pattern",
        help="특정 사용자 ID 패턴을 포함하는 사용자만 필터링합니다. 비워두면 전체 사용자를 표시합니다."
    )

    # 데이터 소스에 따라 다른 정보 표시
    if data_source == "S3 로그 (실제 토큰)":
        st.info(
            "📋 **Amazon Q Developer S3 로그 분석** (실제 토큰 사용량)\n\n"
            "이 분석은 S3에 저장된 실제 프롬프트 로그를 읽어 tiktoken으로 토큰을 계산합니다.\n"
            "IDE에서 발생한 Chat 및 Inline 제안의 실제 토큰 사용량을 확인할 수 있습니다."
        )
    else:
        st.info(
            "📋 **Amazon Q Developer Athena 분석** (토큰 추정)\n\n"
            "이 대시보드는 Amazon Q Developer의 사용자 활동 리포트 CSV 파일을 기반으로 합니다.\n"
            "CSV 리포트는 매일 자정(UTC)에 생성되며 S3 버킷에 저장됩니다."
        )

    # 분석 실행
    if st.sidebar.button("🔍 데이터 분석", type="primary", key="qcli_analyze"):
        logger.info("QCli Analysis button clicked")

        # 데이터 소스별로 다른 분석 로직 실행
        if data_source == "S3 로그 (실제 토큰)":
            # ===== S3 로그 분석 =====
            with st.spinner("S3에서 Amazon Q Developer 프롬프트 로그 분석 중..."):

                # 사용자 패턴 정보 표시
                if user_pattern:
                    st.info(f"🔍 사용자 ID 패턴 필터링 적용: '{user_pattern}'")

                # S3 로그 분석기 초기화
                try:
                    s3_analyzer = QCliS3LogAnalyzer(region=selected_region, logger=logger)

                    # 날짜를 datetime으로 변환
                    from datetime import datetime, timedelta
                    start_dt = datetime.combine(start_date, datetime.min.time())
                    end_dt = datetime.combine(end_date, datetime.max.time())

                    # S3 로그 분석 실행
                    stats = s3_analyzer.analyze_usage(
                        start_dt,
                        end_dt,
                        user_pattern if user_pattern else None
                    )

                    # 결과 표시
                    st.header("📊 전체 요약")

                    col1, col2, col3, col4 = st.columns(4)

                    with col1:
                        st.metric("총 요청 수", f"{stats['total_requests']:,}")

                    with col2:
                        st.metric("Chat 요청", f"{stats['by_type']['chat']['count']:,}")

                    with col3:
                        st.metric("Inline 제안", f"{stats['by_type']['inline']['count']:,}")

                    with col4:
                        st.metric("분석된 파일", f"{stats['total_log_files']:,}")

                    # 토큰 사용량
                    st.header("🔢 실제 토큰 사용량")

                    col5, col6, col7 = st.columns(3)

                    with col5:
                        st.metric("Input 토큰", f"{stats['total_input_tokens']:,}")

                    with col6:
                        st.metric("Output 토큰", f"{stats['total_output_tokens']:,}")

                    with col7:
                        st.metric("총 토큰", f"{stats['total_tokens']:,}")

                    # Context Window 사용률
                    st.subheader("📈 Context Window 분석")
                    context_window = 200000
                    usage_rate = (stats['total_tokens'] / context_window) * 100

                    st.metric(
                        "누적 토큰 사용률",
                        f"{usage_rate:.2f}%",
                        help=f"총 {stats['total_tokens']:,} 토큰 / Context Window {context_window:,} 토큰"
                    )

                    # 기간 일수 계산
                    days_in_period = stats['period']['days']
                    daily_avg = stats['total_tokens'] / days_in_period if days_in_period > 0 else 0
                    daily_usage_rate = (daily_avg / context_window) * 100

                    col_ctx1, col_ctx2 = st.columns(2)
                    with col_ctx1:
                        st.metric("일일 평균 토큰", f"{daily_avg:,.0f}")
                    with col_ctx2:
                        st.metric("일일 평균 사용률", f"{daily_usage_rate:.2f}%")

                    st.info(
                        f"💡 **Context Window 정보**\n\n"
                        f"- Context Window: **200,000 토큰 / 세션**\n"
                        f"- 누적 사용량: **{stats['total_tokens']:,} 토큰** (기간: {days_in_period}일)\n"
                        f"- 일일 평균: **{daily_avg:,.0f} 토큰** ({daily_usage_rate:.2f}%)\n\n"
                        f"⚠️ Context Window는 **세션별로 독립 관리**되므로, 누적 사용률보다 **세션당 사용률**이 중요합니다."
                    )

                    # 타입별 상세 분석
                    st.header("📊 타입별 상세 분석")

                    # Chat 분석
                    st.subheader("💬 Chat (대화)")
                    chat_stats = stats['by_type']['chat']
                    chat_avg_input = chat_stats['input_tokens'] / chat_stats['count'] if chat_stats['count'] > 0 else 0
                    chat_avg_output = chat_stats['output_tokens'] / chat_stats['count'] if chat_stats['count'] > 0 else 0
                    chat_avg_total = (chat_stats['input_tokens'] + chat_stats['output_tokens']) / chat_stats['count'] if chat_stats['count'] > 0 else 0

                    col_chat1, col_chat2, col_chat3, col_chat4 = st.columns(4)
                    with col_chat1:
                        st.metric("요청 수", f"{chat_stats['count']:,}")
                    with col_chat2:
                        st.metric("평균 입력", f"{chat_avg_input:.0f} 토큰")
                    with col_chat3:
                        st.metric("평균 출력", f"{chat_avg_output:.0f} 토큰")
                    with col_chat4:
                        st.metric("평균 총합", f"{chat_avg_total:.0f} 토큰")

                    # Inline 분석
                    st.subheader("⚡ Inline 제안 (코드 자동완성)")
                    inline_stats = stats['by_type']['inline']
                    inline_avg_input = inline_stats['input_tokens'] / inline_stats['count'] if inline_stats['count'] > 0 else 0
                    inline_avg_output = inline_stats['output_tokens'] / inline_stats['count'] if inline_stats['count'] > 0 else 0

                    col_inline1, col_inline2, col_inline3 = st.columns(3)
                    with col_inline1:
                        st.metric("요청 수", f"{inline_stats['count']:,}")
                    with col_inline2:
                        st.metric("평균 컨텍스트", f"{inline_avg_input:.0f} 토큰")
                    with col_inline3:
                        if inline_avg_output == 0:
                            st.metric("평균 출력", "로그에 없음", help="Inline 제안의 응답은 로그에 기록되지 않습니다")
                        else:
                            st.metric("평균 출력", f"{inline_avg_output:.0f} 토큰")

                    # 사용자별 분석
                    if stats['by_user']:
                        st.header("👥 사용자별 분석")

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
                        user_df = user_df.sort_values('총 토큰', ascending=False)
                        st.dataframe(user_df, use_container_width=True)

                    # 날짜별 분석
                    if stats['by_date']:
                        st.header("📅 일별 사용 패턴")

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
                        date_df = date_df.sort_values('날짜')
                        st.dataframe(date_df, use_container_width=True)

                        # 일별 토큰 사용량 차트
                        import plotly.express as px
                        fig = px.line(
                            date_df,
                            x='날짜',
                            y='총 토큰',
                            title='일별 총 토큰 사용량',
                            markers=True
                        )
                        fig.update_xaxes(tickangle=45)
                        st.plotly_chart(fig, use_container_width=True)

                    # 시간대별 분석
                    if stats['by_hour']:
                        st.header("⏰ 시간대별 사용 패턴 (UTC)")

                        hour_data = []
                        for hour, count in stats['by_hour'].items():
                            hour_int = int(hour)
                            kst_hour = (hour_int + 9) % 24
                            hour_data.append({
                                'UTC 시간': f"{hour_int:02d}:00",
                                'KST 시간': f"{kst_hour:02d}:00",
                                '요청 수': count
                            })

                        hour_df = pd.DataFrame(hour_data)
                        hour_df = hour_df.sort_values('UTC 시간')

                        # 테이블
                        st.dataframe(hour_df, use_container_width=True)

                        # 시간대별 요청 수 차트
                        fig = px.bar(
                            hour_df,
                            x='KST 시간',
                            y='요청 수',
                            title='시간대별 요청 수 (한국 시간)',
                            labels={'KST 시간': '시간대', '요청 수': '요청 수'}
                        )
                        fig.update_xaxes(tickangle=45)
                        st.plotly_chart(fig, use_container_width=True)

                    # 가상 비용 계산 (참고용)
                    st.header("💰 가상 비용 분석 (참고용)")
                    st.info(
                        "💡 **참고**: Amazon Q Developer Pro는 **$19/월 정액제**입니다.\n\n"
                        "아래 비용은 Claude API를 직접 사용했을 경우를 가정한 가상 비용입니다."
                    )

                    # Claude Sonnet 3.5 가격 기준
                    MODEL_PRICING = {
                        "input": 0.003 / 1000,  # $0.003 per 1K tokens
                        "output": 0.015 / 1000,  # $0.015 per 1K tokens
                    }

                    virtual_cost = (
                        stats['total_input_tokens'] * MODEL_PRICING['input'] +
                        stats['total_output_tokens'] * MODEL_PRICING['output']
                    )

                    col_cost1, col_cost2, col_cost3 = st.columns(3)

                    with col_cost1:
                        st.metric("Input 비용", f"${stats['total_input_tokens'] * MODEL_PRICING['input']:.2f}")

                    with col_cost2:
                        st.metric("Output 비용", f"${stats['total_output_tokens'] * MODEL_PRICING['output']:.2f}")

                    with col_cost3:
                        st.metric("총 가상 비용", f"${virtual_cost:.2f}")

                    # ROI 비교
                    st.subheader("📊 ROI 분석")
                    subscription_cost = 19.0  # $19/월
                    prorated_subscription = subscription_cost * (days_in_period / 30)

                    col_roi1, col_roi2, col_roi3 = st.columns(3)

                    with col_roi1:
                        st.metric("구독료 (기간 일할)", f"${prorated_subscription:.2f}")

                    with col_roi2:
                        st.metric("가상 사용 비용", f"${virtual_cost:.2f}")

                    with col_roi3:
                        savings = virtual_cost - prorated_subscription
                        if savings > 0:
                            st.metric("절감액", f"${savings:.2f}", delta=f"{(savings/virtual_cost)*100:.1f}% 절감")
                        else:
                            st.metric("손실", f"${-savings:.2f}", delta=f"{(-savings/prorated_subscription)*100:.1f}% 손실", delta_color="inverse")

                except Exception as e:
                    logger.error(f"S3 로그 분석 중 오류: {e}", exc_info=True)
                    st.error(f"S3 로그 분석 중 오류가 발생했습니다: {e}")
                    st.info("프롬프트 로깅이 활성화되어 있는지, S3 버킷에 로그 파일이 있는지 확인하세요.")

        else:
            # ===== 기존 Athena CSV 분석 =====
            with st.spinner("Athena에서 Amazon Q CLI 데이터 분석 중..."):

                # 사용자 패턴 정보 표시
                if user_pattern:
                    st.info(f"🔍 사용자 ID 패턴 필터링 적용: '{user_pattern}'")

                # Tracker 초기화
                tracker = QCliAthenaTracker(region=selected_region)

                # 전체 요약
                summary = tracker.get_total_summary(
                    start_date, end_date, user_pattern if user_pattern else None
                )

                # 조회 기간 일수 계산
                days_in_period = (end_date - start_date).days + 1

                # 리밋 체크
                limit_check = tracker.check_official_limits(summary, days_in_period)

                # 추세 분석
                trends = tracker.analyze_usage_trends(start_date, end_date, user_pattern if user_pattern else None)

                # 사용자별 분석
                user_df = tracker.get_user_usage_analysis(
                    start_date, end_date, user_pattern if user_pattern else None
                )

                # 기능별 사용 통계
                feature_df = tracker.get_feature_usage_stats(
                    start_date, end_date, user_pattern if user_pattern else None
                )

                # 일별 사용 패턴
                daily_df = tracker.get_daily_usage_pattern(
                    start_date, end_date, user_pattern if user_pattern else None
                )

                # 토큰 추정
                token_estimate = tracker.estimate_tokens(summary, "average")

            st.header("📊 전체 요약")

            col1, col2, col3, col4 = st.columns(4)

            with col1:
                st.metric("채팅 메시지", f"{summary['total_chat_messages']:,}")

            with col2:
                st.metric("인라인 제안", f"{summary['total_inline_suggestions']:,}")

            with col3:
                st.metric("활성 사용자", f"{summary['unique_users']:,}")

            with col4:
                st.metric("활동 일수", f"{summary['active_days']:,}")

            col5, col6, col7, col8 = st.columns(4)

            with col5:
                st.metric("채팅 코드 라인", f"{summary['total_chat_code_lines']:,}")

            with col6:
                st.metric("인라인 코드 라인", f"{summary['total_inline_code_lines']:,}")

            with col7:
                st.metric("/dev 이벤트", f"{summary['total_dev_events']:,}")

            with col8:
                st.metric("/test 이벤트", f"{summary['total_test_events']:,}")

            # 리밋 추적 섹션 (새로 추가)
            st.header("⚠️ 공식 리밋 모니터링")

            # 리밋 상태 표시
            col_limit1, col_limit2 = st.columns(2)

            with col_limit1:
                st.subheader("🔧 /dev 명령어")
                dev_limit = limit_check["dev_events"]

                # 경고 색상
                if dev_limit["warning"]:
                    st.error(f"⚠️ 경고: 월간 리밋의 {dev_limit['percentage']:.1f}% 도달!")
                elif dev_limit["percentage"] > 50:
                    st.warning(f"주의: 월간 리밋의 {dev_limit['percentage']:.1f}%")
                else:
                    st.success(f"정상: 월간 리밋의 {dev_limit['percentage']:.1f}%")

                st.metric(
                    "현재 사용량 / 월간 리밋",
                    f"{dev_limit['used']} / {dev_limit['limit']}회"
                )
                st.metric(
                    "월간 예상 사용량",
                    f"{dev_limit['projected_monthly']}회",
                    delta=f"{dev_limit['projected_monthly'] - dev_limit['limit']}회 여유" if dev_limit['projected_monthly'] < dev_limit['limit'] else f"{dev_limit['projected_monthly'] - dev_limit['limit']}회 초과 예상"
                )

            with col_limit2:
                st.subheader("🔄 Code Transformation")
                trans_limit = limit_check["transformation_lines"]

                # 경고 색상
                if trans_limit["warning"]:
                    st.error(f"⚠️ 경고: 월간 리밋의 {trans_limit['percentage']:.1f}% 도달!")
                elif trans_limit["percentage"] > 50:
                    st.warning(f"주의: 월간 리밋의 {trans_limit['percentage']:.1f}%")
                else:
                    st.success(f"정상: 월간 리밋의 {trans_limit['percentage']:.1f}%")

                st.metric(
                    "현재 사용량 / 월간 리밋",
                    f"{trans_limit['used']:,} / {trans_limit['limit']:,}줄"
                )
                st.metric(
                    "월간 예상 사용량",
                    f"{trans_limit['projected_monthly']:,}줄",
                    delta=f"{trans_limit['projected_monthly'] - trans_limit['limit']:,}줄 여유" if trans_limit['projected_monthly'] < trans_limit['limit'] else f"{trans_limit['projected_monthly'] - trans_limit['limit']:,}줄 초과 예상"
                )

            # 사용 패턴 분석
            st.subheader("📈 사용 패턴 분석")

            col_trend1, col_trend2, col_trend3 = st.columns(3)

            with col_trend1:
                st.metric("일일 평균 활동", f"{trends['daily_avg']:.1f}건")

            with col_trend2:
                st.metric("최대 활동일", f"{trends['daily_max']:.0f}건")

            with col_trend3:
                if trends["anomaly_detected"]:
                    st.error(f"⚠️ 이상 감지: {trends['anomaly_count']}일")
                else:
                    st.success("✅ 정상 패턴")

            if trends["anomaly_detected"]:
                st.warning(
                    f"🚨 **사용량 급증 감지**: {trends['anomaly_count']}일 동안 일평균({trends['daily_avg']:.1f})의 "
                    f"3배({trends['anomaly_threshold']:.1f})를 초과했습니다. "
                    f"리밋 도달 가능성이 높습니다!"
                )

            # 주요 안내 사항
            st.info(
                "💡 **리밋 정보**\n\n"
                "- **채팅/인라인 제안**: AWS가 공식 리밋을 공개하지 않음 (추적 불가)\n"
                "- **/dev 명령어**: 30회/월 (공식 문서)\n"
                "- **Code Transformation**: 4,000줄/월 (공식 문서)\n\n"
                "📊 **이 대시보드는 CSV 데이터 기반으로 간접 추정**만 가능합니다.\n"
                "실제 리밋 도달 시 AWS 콘솔에서 'Monthly limit reached' 메시지를 받게 됩니다."
            )

            # 토큰 사용량 추정 (참고용으로 변경)
            st.header("🔢 토큰 사용량 추정 (참고용)")
            st.info(
                "💡 **참고**: Amazon Q Developer Pro는 **$19/월 정액제**입니다.\n\n"
                "아래 토큰 추정치는 실제 청구 비용과 무관하며, 다음 용도로만 사용됩니다:\n"
                "- ROI 분석: 구독료 대비 얼마나 많이 사용하는가?\n"
                "- 가상 비교: Claude API를 직접 사용했다면 얼마가 나왔을까?\n"
                "- 사용량 파악: 대략적인 토큰 사용 규모 이해"
            )

            # 평균 추정치만 계산
            token_estimate = tracker.estimate_tokens(summary, "average")

            # 가상 비용 계산 (Claude Sonnet 3.5 가격 기준)
            MODEL_PRICING = {
                "input": 0.003 / 1000,  # $0.003 per 1K tokens
                "output": 0.015 / 1000,  # $0.015 per 1K tokens
            }
            virtual_cost = (
                token_estimate['estimated_input_tokens'] * MODEL_PRICING['input'] +
                token_estimate['estimated_output_tokens'] * MODEL_PRICING['output']
            )

            # 추정치 표시
            col_est1, col_est2, col_est3, col_est4 = st.columns(4)

            with col_est1:
                st.metric("Input 토큰", f"{token_estimate['estimated_input_tokens']:,}")

            with col_est2:
                st.metric("Output 토큰", f"{token_estimate['estimated_output_tokens']:,}")

            with col_est3:
                st.metric("총 토큰", f"{token_estimate['estimated_total_tokens']:,}")

            with col_est4:
                st.metric("가상 비용 (Claude API)", f"${virtual_cost:.2f}")

            # ROI 비교
            st.subheader("💰 ROI 분석")
            subscription_cost = 19.0  # $19/월
            days_in_period = (end_date - start_date).days + 1
            prorated_subscription = subscription_cost * (days_in_period / 30)

            col_roi1, col_roi2, col_roi3 = st.columns(3)

            with col_roi1:
                st.metric("구독료 (기간 일할)", f"${prorated_subscription:.2f}")

            with col_roi2:
                st.metric("가상 사용 비용", f"${virtual_cost:.2f}")

            with col_roi3:
                savings = virtual_cost - prorated_subscription
                if savings > 0:
                    st.metric("절감액", f"${savings:.2f}", delta=f"{(savings/virtual_cost)*100:.1f}% 절감")
                else:
                    st.metric("손실", f"${-savings:.2f}", delta=f"{(-savings/prorated_subscription)*100:.1f}% 손실", delta_color="inverse")

            # 사용자별 분석
            st.header("👥 사용자별 분석")

            user_df = tracker.get_user_usage_analysis(
                start_date, end_date, user_pattern if user_pattern else None
            )

            if not user_df.empty:
                # 숫자 컬럼 변환
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
                        user_df[col] = pd.to_numeric(user_df[col], errors="coerce").fillna(0)

                st.dataframe(user_df, use_container_width=True)

                # 사용자별 활동 차트
                if len(user_df) > 0:
                    import plotly.express as px

                    fig = px.bar(
                        user_df.head(10),
                        x="user_id",
                        y="total_chat_messages",
                        title="상위 10명 사용자별 채팅 메시지 수",
                        labels={"user_id": "사용자 ID", "total_chat_messages": "채팅 메시지 수"},
                    )
                    fig.update_xaxes(tickangle=45)
                    st.plotly_chart(fig, use_container_width=True)

                    # Chat vs Inline 코드 라인 비교
                    fig2 = px.bar(
                        user_df.head(10),
                        x="user_id",
                        y=["total_chat_code_lines", "total_inline_code_lines"],
                        title="상위 10명 사용자별 코드 라인 생성 (Chat vs Inline)",
                        labels={"value": "코드 라인 수", "user_id": "사용자 ID"},
                        barmode="group",
                    )
                    fig2.update_xaxes(tickangle=45)
                    st.plotly_chart(fig2, use_container_width=True)
            else:
                st.info("분석할 사용자 데이터가 없습니다.")

            # 기능별 사용 통계
            st.header("📱 기능별 사용 통계")

            feature_df = tracker.get_feature_usage_stats(
                start_date, end_date, user_pattern if user_pattern else None
            )

            if not feature_df.empty:
                # 숫자 컬럼 변환
                for col in ["total_count", "unique_users"]:
                    if col in feature_df.columns:
                        feature_df[col] = pd.to_numeric(feature_df[col], errors="coerce").fillna(0)

                st.dataframe(feature_df, use_container_width=True)

                # 기능별 사용량 파이 차트
                if len(feature_df) > 0:
                    import plotly.express as px

                    fig = px.pie(
                        feature_df,
                        values="total_count",
                        names="feature_type",
                        title="기능별 사용 비율",
                    )
                    st.plotly_chart(fig, use_container_width=True)
            else:
                st.info("분석할 기능 데이터가 없습니다.")

            # 일별 사용 패턴
            st.header("📅 일별 사용 패턴")

            daily_df = tracker.get_daily_usage_pattern(
                start_date, end_date, user_pattern if user_pattern else None
            )

            if not daily_df.empty and len(daily_df) > 0:
                # 숫자 컬럼 변환
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
                        daily_df[col] = pd.to_numeric(daily_df[col], errors="coerce").fillna(0)

                # 날짜를 datetime으로 변환 (MM-DD-YYYY 형식)
                daily_df["date"] = pd.to_datetime(daily_df["date_str"], format='%m-%d-%Y')

                # 표시용 DataFrame 생성
                display_df = daily_df.copy()
                display_df["날짜"] = display_df["date"].dt.strftime("%Y-%m-%d")
                display_df = display_df[
                    ["날짜", "total_chat_messages", "total_inline_suggestions", "total_inline_acceptances", "unique_users"]
                ]
                display_df.columns = ["날짜", "채팅 메시지", "인라인 제안", "인라인 수락", "활성 사용자"]

                # 1. 테이블 먼저 표시
                st.dataframe(display_df, use_container_width=True)

                # 2. 그래프 표시
                import plotly.express as px
                import plotly.graph_objects as go

                # 일별 채팅 메시지 패턴
                fig = px.line(
                    daily_df,
                    x="date",
                    y="total_chat_messages",
                    title="일별 채팅 메시지 수",
                    labels={"date": "날짜", "total_chat_messages": "채팅 메시지 수"},
                    markers=True,
                )
                st.plotly_chart(fig, use_container_width=True)

                # 일별 인라인 제안 vs 수락
                fig2 = go.Figure()
                fig2.add_trace(
                    go.Scatter(
                        x=daily_df["date"],
                        y=daily_df["total_inline_suggestions"],
                        mode="lines+markers",
                        name="인라인 제안",
                        line=dict(color="blue"),
                    )
                )
                fig2.add_trace(
                    go.Scatter(
                        x=daily_df["date"],
                        y=daily_df["total_inline_acceptances"],
                        mode="lines+markers",
                        name="인라인 수락",
                        line=dict(color="green"),
                    )
                )
                fig2.update_layout(
                    title="일별 인라인 코드 제안 vs 수락",
                    xaxis_title="날짜",
                    yaxis_title="개수",
                    hovermode="x unified",
                )
                st.plotly_chart(fig2, use_container_width=True)

                # 일별 활성 사용자 수
                fig3 = px.bar(
                    daily_df,
                    x="date",
                    y="unique_users",
                    title="일별 활성 사용자 수",
                    labels={"date": "날짜", "unique_users": "활성 사용자 수"},
                )
                st.plotly_chart(fig3, use_container_width=True)
            else:
                st.warning("선택한 기간에 일별 사용 데이터가 없습니다.")

    else:
        # 초기 화면
        st.info(
            "👈 왼쪽 사이드바에서 리전과 날짜 범위를 선택한 후 '데이터 분석' 버튼을 클릭하세요."
        )

        st.markdown("### 🛠️ 환경 설정 가이드")

        st.markdown("#### 1️⃣ Amazon Q Developer 설정")
        st.markdown(
            """
        1. **Amazon Q Developer 콘솔**에서 "Collect granular metrics per user" 옵션 활성화
        2. **S3 버킷 지정**: 사용자 활동 리포트가 저장될 S3 버킷 설정
        3. **매일 자정(UTC)**에 CSV 리포트가 자동으로 생성됩니다
        """
        )

        st.markdown("#### 2️⃣ 분석 환경 구축")
        st.code(
            """
# Amazon Q CLI 분석 환경 설정
python setup_qcli_analytics.py --region us-east-1

# 대시보드 실행
streamlit run bedrock_tracker.py
        """,
            language="bash",
        )

        st.markdown("#### 3️⃣ 데이터 소스")
        st.markdown(
            """
        **CSV 리포트 (사용자 활동)**:
        - 일별 사용자별 요청 수
        - Agentic 요청 수
        - CLI/IDE 요청 수
        - 코드 제안 수
        """
        )

        st.markdown("### 📋 주요 메트릭")
        st.markdown(
            """
        - **총 요청 수**: 전체 Amazon Q 요청 수
        - **Agentic 요청**: Q&A 챗 또는 agentic 코딩 상호작용
        - **CLI 요청**: Amazon Q CLI를 통한 요청
        - **IDE 요청**: IDE 플러그인을 통한 요청
        - **코드 제안**: 코드 자동 완성 제안 수
        """
        )

    logger.info("QCli Dashboard rendering complete")


if __name__ == "__main__":
    main()

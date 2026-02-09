"""
Amazon Q Developer S3 로그 분석 모듈 (bedrock_tracker용)

S3에 저장된 프롬프트 로그를 직접 분석하여 실제 토큰 사용량을 계산합니다.
"""

import boto3
import json
import gzip
from datetime import datetime, timedelta
from typing import Dict, List
from pathlib import Path
from collections import defaultdict
import logging

try:
    import tiktoken
    TIKTOKEN_AVAILABLE = True
except ImportError:
    TIKTOKEN_AVAILABLE = False
    logging.warning("tiktoken not available, using fallback token estimation")


class QCliS3LogAnalyzer:
    """Amazon Q Developer S3 프롬프트 로그 분석기"""

    def __init__(self, region='us-east-1', logger=None):
        """
        Args:
            region: AWS 리전
            logger: 로거 인스턴스 (None이면 기본 로거 사용)
        """
        self.region = region
        self.s3 = boto3.client('s3', region_name=region)

        # 계정 ID 가져오기
        sts = boto3.client('sts', region_name=region)
        self.account_id = sts.get_caller_identity()['Account']
        self.bucket_name = f'amazonq-developer-reports-{self.account_id}'
        self.log_prefix = 'prompt_logging/AWSLogs'

        # 로거 설정
        self.logger = logger if logger else logging.getLogger(__name__)

        # tiktoken 인코더
        if TIKTOKEN_AVAILABLE:
            try:
                self.encoding = tiktoken.get_encoding("cl100k_base")
            except:
                self.encoding = None
                self.logger.warning("Failed to load tiktoken encoder")
        else:
            self.encoding = None

    def estimate_tokens(self, text: str) -> int:
        """텍스트의 토큰 수 추정"""
        if not text:
            return 0

        if self.encoding:
            try:
                return len(self.encoding.encode(text))
            except:
                pass

        # Fallback: 대략적인 추정 (1토큰 ≈ 3글자)
        return len(text) // 3

    def list_log_files(
        self,
        start_date: datetime,
        end_date: datetime,
        log_type: str = None
    ) -> List[str]:
        """
        S3에서 날짜 범위에 해당하는 로그 파일 목록 가져오기

        Args:
            start_date: 시작 날짜
            end_date: 종료 날짜
            log_type: 로그 타입 ("GenerateAssistantResponse", "GenerateCompletions", None=all)

        Returns:
            S3 키 리스트
        """
        self.logger.info(f"Listing log files from {start_date} to {end_date}")

        log_files = []

        try:
            # 날짜 범위 생성
            current_date = start_date
            while current_date <= end_date:
                year = current_date.strftime('%Y')
                month = current_date.strftime('%m')
                day = current_date.strftime('%d')

                # 로그 타입별로 검색
                log_types = [log_type] if log_type else ['GenerateAssistantResponse', 'GenerateCompletions']

                for lt in log_types:
                    prefix = f"{self.log_prefix}/{self.account_id}/QDeveloperLogs/{lt}/us-east-1/{year}/{month}/{day}/"

                    # S3 객체 나열
                    paginator = self.s3.get_paginator('list_objects_v2')
                    pages = paginator.paginate(Bucket=self.bucket_name, Prefix=prefix)

                    for page in pages:
                        if 'Contents' in page:
                            for obj in page['Contents']:
                                if obj['Key'].endswith('.json.gz'):
                                    log_files.append(obj['Key'])

                current_date += timedelta(days=1)

            self.logger.info(f"Found {len(log_files)} log files")
            return log_files

        except Exception as e:
            self.logger.error(f"Error listing log files: {e}")
            return []

    def parse_log_file(self, s3_key: str) -> List[Dict]:
        """S3에서 로그 파일 다운로드 및 파싱"""
        results = []

        try:
            # S3에서 객체 가져오기
            response = self.s3.get_object(Bucket=self.bucket_name, Key=s3_key)

            # gzip 압축 해제 및 JSON 파싱
            with gzip.GzipFile(fileobj=response['Body']) as gzipfile:
                content = gzipfile.read().decode('utf-8')
                data = json.loads(content)

            for record in data.get('records', []):
                # Chat 로그 (GenerateAssistantResponse)
                if 'generateAssistantResponseEventRequest' in record:
                    request = record['generateAssistantResponseEventRequest']
                    response_data = record.get('generateAssistantResponseEventResponse', {})

                    prompt = request.get('prompt', '')
                    assistant_response = response_data.get('assistantResponse', '')

                    results.append({
                        'type': 'chat',
                        'input_tokens': self.estimate_tokens(prompt),
                        'output_tokens': self.estimate_tokens(assistant_response),
                        'timestamp': request.get('timeStamp'),
                        'userId': request.get('userId'),
                        'conversationId': response_data.get('messageMetadata', {}).get('conversationId')
                    })

                # Inline 제안 로그 (GenerateCompletions)
                elif 'generateCompletionsEventRequest' in record:
                    request = record['generateCompletionsEventRequest']
                    response_data = record.get('generateCompletionsEventResponse', {})

                    left_context = request.get('leftContext', '')
                    right_context = request.get('rightContext', '')
                    completions = response_data.get('completions', [])

                    completion_text = '\n'.join([
                        c.get('content', '') for c in completions
                    ])

                    results.append({
                        'type': 'inline',
                        'input_tokens': self.estimate_tokens(left_context + right_context),
                        'output_tokens': self.estimate_tokens(completion_text),
                        'timestamp': request.get('timeStamp'),
                        'userId': request.get('userId'),
                        'fileName': request.get('fileName')
                    })

        except Exception as e:
            self.logger.debug(f"Error parsing log file {s3_key}: {e}")

        return results

    def analyze_usage(
        self,
        start_date: datetime,
        end_date: datetime,
        user_pattern: str = None
    ) -> Dict:
        """
        지정된 기간의 사용량 분석

        Args:
            start_date: 시작 날짜
            end_date: 종료 날짜
            user_pattern: 사용자 ID 필터 패턴

        Returns:
            사용량 통계 딕셔너리
        """
        self.logger.info(f"Analyzing usage from {start_date} to {end_date}")

        # 로그 파일 목록 가져오기
        log_files = self.list_log_files(start_date, end_date)

        if not log_files:
            self.logger.warning("No log files found")
            return self._empty_stats()

        # 통계 초기화
        stats = {
            'period': {
                'start': start_date.isoformat(),
                'end': end_date.isoformat(),
                'days': (end_date - start_date).days + 1
            },
            'total_log_files': len(log_files),
            'total_requests': 0,
            'by_type': {
                'chat': {'count': 0, 'input_tokens': 0, 'output_tokens': 0},
                'inline': {'count': 0, 'input_tokens': 0, 'output_tokens': 0}
            },
            'by_user': defaultdict(lambda: {
                'requests': 0,
                'input_tokens': 0,
                'output_tokens': 0
            }),
            'by_date': defaultdict(lambda: {
                'requests': 0,
                'input_tokens': 0,
                'output_tokens': 0
            }),
            'by_hour': defaultdict(int),
            'total_input_tokens': 0,
            'total_output_tokens': 0,
            'total_tokens': 0
        }

        # 로그 파일 분석 (샘플링: 너무 많으면 일부만)
        max_files = 500  # 최대 500개 파일만 분석
        sample_files = log_files if len(log_files) <= max_files else log_files[::len(log_files)//max_files]

        self.logger.info(f"Processing {len(sample_files)} log files (total: {len(log_files)})")

        for i, log_file in enumerate(sample_files):
            if i % 50 == 0:
                self.logger.info(f"Processing file {i+1}/{len(sample_files)}")

            records = self.parse_log_file(log_file)

            for record in records:
                # 사용자 필터 적용
                if user_pattern and record.get('userId'):
                    if user_pattern.lower() not in record['userId'].lower():
                        continue

                log_type = record['type']
                user_id = record.get('userId', 'unknown')
                timestamp = record.get('timestamp', '')

                # 기본 통계
                stats['total_requests'] += 1
                stats['by_type'][log_type]['count'] += 1
                stats['by_type'][log_type]['input_tokens'] += record['input_tokens']
                stats['by_type'][log_type]['output_tokens'] += record['output_tokens']

                # 사용자별 통계
                stats['by_user'][user_id]['requests'] += 1
                stats['by_user'][user_id]['input_tokens'] += record['input_tokens']
                stats['by_user'][user_id]['output_tokens'] += record['output_tokens']

                # 날짜별 통계
                if timestamp:
                    try:
                        date_str = timestamp.split('T')[0]
                        stats['by_date'][date_str]['requests'] += 1
                        stats['by_date'][date_str]['input_tokens'] += record['input_tokens']
                        stats['by_date'][date_str]['output_tokens'] += record['output_tokens']

                        # 시간대별 통계
                        hour = timestamp.split('T')[1].split(':')[0]
                        stats['by_hour'][hour] += 1
                    except:
                        pass

        # 총합 계산
        for type_stats in stats['by_type'].values():
            stats['total_input_tokens'] += type_stats['input_tokens']
            stats['total_output_tokens'] += type_stats['output_tokens']

        stats['total_tokens'] = stats['total_input_tokens'] + stats['total_output_tokens']

        # defaultdict를 일반 dict로 변환
        stats['by_user'] = dict(stats['by_user'])
        stats['by_date'] = dict(sorted(stats['by_date'].items()))
        stats['by_hour'] = dict(sorted(stats['by_hour'].items()))

        # 샘플링 비율 적산 (전체 파일 수에 맞게 스케일링)
        if len(sample_files) < len(log_files):
            scale_factor = len(log_files) / len(sample_files)
            self.logger.info(f"Scaling results by factor: {scale_factor:.2f}")

            stats['total_requests'] = int(stats['total_requests'] * scale_factor)
            stats['total_input_tokens'] = int(stats['total_input_tokens'] * scale_factor)
            stats['total_output_tokens'] = int(stats['total_output_tokens'] * scale_factor)
            stats['total_tokens'] = int(stats['total_tokens'] * scale_factor)

            for type_name in stats['by_type']:
                stats['by_type'][type_name]['count'] = int(stats['by_type'][type_name]['count'] * scale_factor)
                stats['by_type'][type_name]['input_tokens'] = int(stats['by_type'][type_name]['input_tokens'] * scale_factor)
                stats['by_type'][type_name]['output_tokens'] = int(stats['by_type'][type_name]['output_tokens'] * scale_factor)

        return stats

    def _empty_stats(self) -> Dict:
        """빈 통계 딕셔너리 반환"""
        return {
            'period': {},
            'total_log_files': 0,
            'total_requests': 0,
            'by_type': {
                'chat': {'count': 0, 'input_tokens': 0, 'output_tokens': 0},
                'inline': {'count': 0, 'input_tokens': 0, 'output_tokens': 0}
            },
            'by_user': {},
            'by_date': {},
            'by_hour': {},
            'total_input_tokens': 0,
            'total_output_tokens': 0,
            'total_tokens': 0
        }

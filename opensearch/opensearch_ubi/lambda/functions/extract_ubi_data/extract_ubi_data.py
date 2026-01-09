"""
Lambda function to extract UBI queries and events from OpenSearch.

This function:
1. Connects to OpenSearch using credentials from Secrets Manager
2. Extracts unique queries from UBI data
3. Optionally exports data to S3
"""

import json
import logging
import os
from datetime import datetime, timedelta
from typing import Any

import boto3
from opensearchpy import OpenSearch, RequestsHttpConnection
from requests_aws4auth import AWS4Auth

# Configure logging
logger = logging.getLogger()
logger.setLevel(os.environ.get('LOG_LEVEL', 'INFO'))


def get_opensearch_client() -> OpenSearch:
    """Create OpenSearch client with AWS authentication."""
    endpoint = os.environ['OPENSEARCH_ENDPOINT']
    region = os.environ.get('AWS_REGION_NAME', 'us-east-1')

    # Get credentials
    session = boto3.Session()
    credentials = session.get_credentials()

    awsauth = AWS4Auth(
        credentials.access_key,
        credentials.secret_key,
        region,
        'es',
        session_token=credentials.token
    )

    return OpenSearch(
        hosts=[{'host': endpoint, 'port': 443}],
        http_auth=awsauth,
        use_ssl=True,
        verify_certs=True,
        connection_class=RequestsHttpConnection,
        timeout=60
    )


def get_master_credentials() -> dict[str, str]:
    """Get master user credentials from Secrets Manager."""
    secret_arn = os.environ['MASTER_USER_SECRET_ARN']
    region = os.environ.get('AWS_REGION_NAME', 'us-east-1')

    client = boto3.client('secretsmanager', region_name=region)
    response = client.get_secret_value(SecretId=secret_arn)

    return json.loads(response['SecretString'])


def extract_unique_queries(
    client: OpenSearch,
    index: str,
    days: int = 7,
    limit: int = 100
) -> list[dict[str, Any]]:
    """
    Extract unique queries from UBI queries index.

    Args:
        client: OpenSearch client
        index: UBI queries index name
        days: Number of days to look back
        limit: Maximum number of unique queries

    Returns:
        List of unique queries with metadata
    """
    # Calculate date range
    end_date = datetime.utcnow()
    start_date = end_date - timedelta(days=days)

    query = {
        "size": 0,
        "query": {
            "range": {
                "timestamp": {
                    "gte": start_date.isoformat(),
                    "lte": end_date.isoformat()
                }
            }
        },
        "aggs": {
            "unique_queries": {
                "terms": {
                    "field": "user_query.keyword",
                    "size": limit,
                    "order": {"_count": "desc"}
                },
                "aggs": {
                    "latest": {
                        "top_hits": {
                            "size": 1,
                            "_source": ["query_id", "user_id", "session_id", "timestamp"],
                            "sort": [{"timestamp": "desc"}]
                        }
                    },
                    "click_count": {
                        "filter": {
                            "term": {"has_clicks": True}
                        }
                    }
                }
            }
        }
    }

    try:
        response = client.search(index=index, body=query)
        buckets = response['aggregations']['unique_queries']['buckets']

        queries = []
        for bucket in buckets:
            query_text = bucket['key']
            if query_text and len(query_text) > 1:
                latest = bucket['latest']['hits']['hits'][0]['_source'] if bucket['latest']['hits']['hits'] else {}
                queries.append({
                    "query": query_text,
                    "count": bucket['doc_count'],
                    "query_id": latest.get('query_id'),
                    "user_id": latest.get('user_id'),
                    "session_id": latest.get('session_id'),
                    "timestamp": latest.get('timestamp')
                })

        return queries

    except Exception as e:
        logger.error(f"Error extracting queries: {e}")
        return []


def extract_events_for_queries(
    client: OpenSearch,
    index: str,
    query_ids: list[str]
) -> dict[str, list[dict[str, Any]]]:
    """
    Extract events associated with specific query IDs.

    Args:
        client: OpenSearch client
        index: UBI events index name
        query_ids: List of query IDs to get events for

    Returns:
        Dictionary mapping query_id to list of events
    """
    if not query_ids:
        return {}

    query = {
        "size": 10000,
        "query": {
            "terms": {
                "query_id": query_ids
            }
        },
        "sort": [{"timestamp": "asc"}]
    }

    try:
        response = client.search(index=index, body=query)
        hits = response['hits']['hits']

        events_by_query: dict[str, list] = {}
        for hit in hits:
            source = hit['_source']
            query_id = source.get('query_id')
            if query_id:
                if query_id not in events_by_query:
                    events_by_query[query_id] = []
                events_by_query[query_id].append({
                    "action_name": source.get('action_name'),
                    "object_id": source.get('object_id'),
                    "position": source.get('position'),
                    "timestamp": source.get('timestamp'),
                    "event_attributes": source.get('event_attributes', {})
                })

        return events_by_query

    except Exception as e:
        logger.error(f"Error extracting events: {e}")
        return {}


def save_to_s3(data: dict[str, Any], prefix: str) -> str:
    """
    Save data to S3.

    Args:
        data: Data to save
        prefix: S3 key prefix

    Returns:
        S3 URI of saved file
    """
    bucket = os.environ['DATA_BUCKET']
    timestamp = datetime.utcnow().strftime('%Y%m%d_%H%M%S')
    key = f"{prefix}/extract_{timestamp}.json"

    s3 = boto3.client('s3')
    s3.put_object(
        Bucket=bucket,
        Key=key,
        Body=json.dumps(data, default=str),
        ContentType='application/json'
    )

    return f"s3://{bucket}/{key}"


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """
    Lambda handler for UBI data extraction.

    Args:
        event: Lambda event with optional configuration:
            - days: Number of days to look back (default: 7)
            - limit: Maximum queries to extract (default: 100)
            - save_to_s3: Whether to save to S3 (default: False)

    Returns:
        Extraction results
    """
    logger.info(f"Starting UBI data extraction with event: {json.dumps(event)}")

    # Get configuration
    days = event.get('days', 7)
    limit = event.get('limit', 100)
    save_to_s3_flag = event.get('save_to_s3', False)

    # Initialize OpenSearch client
    client = get_opensearch_client()

    # Extract unique queries
    queries_index = os.environ.get('UBI_QUERIES_INDEX', 'ubi_queries')
    events_index = os.environ.get('UBI_EVENTS_INDEX', 'ubi_events')

    logger.info(f"Extracting queries from {queries_index} (last {days} days, limit {limit})")
    queries = extract_unique_queries(client, queries_index, days, limit)
    logger.info(f"Extracted {len(queries)} unique queries")

    # Extract events for queries
    query_ids = [q['query_id'] for q in queries if q.get('query_id')]
    events = extract_events_for_queries(client, events_index, query_ids)
    logger.info(f"Extracted events for {len(events)} queries")

    # Prepare result
    result = {
        "queryCount": len(queries),
        "eventCount": sum(len(e) for e in events.values()),
        "queries": queries,
        "queryIds": query_ids,
        "timestamp": datetime.utcnow().isoformat()
    }

    # Optionally save to S3
    if save_to_s3_flag:
        s3_uri = save_to_s3({
            "queries": queries,
            "events": events,
            "metadata": {
                "extracted_at": result["timestamp"],
                "days": days,
                "limit": limit
            }
        }, "ubi-queries")
        result["s3Uri"] = s3_uri
        logger.info(f"Saved extraction to {s3_uri}")

    return result

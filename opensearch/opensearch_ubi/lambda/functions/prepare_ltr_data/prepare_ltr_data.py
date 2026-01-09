"""
Lambda function to prepare LTR training data from judgments.

This function:
1. Reads judgments from OpenSearch
2. Extracts features for query-document pairs
3. Formats data for LTR model training
4. Optionally saves to S3
"""

import json
import logging
import os
from datetime import datetime
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


def fetch_judgments(
    client: OpenSearch,
    index: str,
    min_rating: float = 0,
    limit: int = 10000
) -> list[dict[str, Any]]:
    """
    Fetch judgments from OpenSearch.

    Args:
        client: OpenSearch client
        index: Judgments index name
        min_rating: Minimum rating to include
        limit: Maximum number of judgments

    Returns:
        List of judgment records
    """
    query = {
        "size": limit,
        "query": {
            "range": {
                "rating": {"gte": min_rating}
            }
        },
        "sort": [{"timestamp": "desc"}]
    }

    try:
        response = client.search(index=index, body=query)
        hits = response['hits']['hits']

        judgments = []
        for hit in hits:
            source = hit['_source']
            judgments.append({
                "query": source.get('query'),
                "doc_id": source.get('doc_id'),
                "rating": source.get('rating'),
                "rank": source.get('rank'),
                "product_name": source.get('product_name'),
                "timestamp": source.get('timestamp')
            })

        return judgments

    except Exception as e:
        logger.error(f"Error fetching judgments: {e}")
        return []


def extract_features(
    client: OpenSearch,
    query: str,
    doc_id: str,
    products_index: str = "products"
) -> dict[str, float]:
    """
    Extract features for a query-document pair.

    Args:
        client: OpenSearch client
        query: Search query
        doc_id: Document ID
        products_index: Products index name

    Returns:
        Dictionary of feature values
    """
    features = {
        "bm25_score": 0.0,
        "title_match": 0.0,
        "description_match": 0.0,
        "category_match": 0.0,
        "brand_match": 0.0,
        "price_log": 0.0,
        "popularity_score": 0.0,
        "recency_score": 0.0
    }

    try:
        # Get document
        doc = client.get(index=products_index, id=doc_id)
        source = doc['_source']

        # Calculate BM25 score using explain API
        explain_body = {
            "query": {
                "multi_match": {
                    "query": query,
                    "fields": ["name^3", "description^2", "category", "brand", "tags"]
                }
            }
        }

        explain_response = client.explain(
            index=products_index,
            id=doc_id,
            body=explain_body
        )

        if explain_response.get('matched'):
            features['bm25_score'] = explain_response.get('explanation', {}).get('value', 0.0)

        # Text matching features
        query_lower = query.lower()
        name = source.get('name', '').lower()
        description = source.get('description', '').lower()
        category = source.get('category', '').lower()
        brand = source.get('brand', '').lower()

        features['title_match'] = 1.0 if query_lower in name else 0.0
        features['description_match'] = 1.0 if query_lower in description else 0.0
        features['category_match'] = 1.0 if query_lower in category else 0.0
        features['brand_match'] = 1.0 if query_lower in brand else 0.0

        # Price feature (log transform)
        price = source.get('price', 0)
        if price > 0:
            import math
            features['price_log'] = math.log(price + 1)

        # Popularity (if available)
        features['popularity_score'] = source.get('popularity', 0.0)

        # Recency (if available)
        features['recency_score'] = source.get('recency_score', 0.5)

    except Exception as e:
        logger.warning(f"Error extracting features for doc {doc_id}: {e}")

    return features


def format_for_ranklib(
    data: list[dict[str, Any]],
    feature_names: list[str]
) -> str:
    """
    Format training data in RankLib format.

    Format: <rating> qid:<query_id> 1:<feature1> 2:<feature2> ... # <doc_id>

    Args:
        data: List of training records
        feature_names: List of feature names in order

    Returns:
        RankLib formatted string
    """
    lines = []
    query_id_map = {}
    current_qid = 0

    for record in data:
        query = record['query']
        if query not in query_id_map:
            current_qid += 1
            query_id_map[query] = current_qid

        qid = query_id_map[query]
        rating = int(record['rating'])
        doc_id = record['doc_id']
        features = record['features']

        # Build feature string
        feature_parts = []
        for i, name in enumerate(feature_names, 1):
            value = features.get(name, 0.0)
            feature_parts.append(f"{i}:{value:.6f}")

        feature_str = " ".join(feature_parts)
        line = f"{rating} qid:{qid} {feature_str} # {doc_id}"
        lines.append(line)

    return "\n".join(lines)


def save_to_s3(content: str, bucket: str, key: str) -> str:
    """Save content to S3."""
    s3 = boto3.client('s3')
    s3.put_object(
        Bucket=bucket,
        Key=key,
        Body=content,
        ContentType='text/plain'
    )
    return f"s3://{bucket}/{key}"


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """
    Lambda handler for LTR data preparation.

    Args:
        event: Lambda event containing optional configuration

    Returns:
        Data preparation results
    """
    logger.info(f"Starting LTR data preparation with event keys: {list(event.keys())}")

    # Get configuration
    judgments_index = os.environ.get('JUDGMENTS_INDEX', 'llm_judgments')
    products_index = os.environ.get('PRODUCTS_INDEX', 'products')
    data_bucket = os.environ.get('DATA_BUCKET')

    # Initialize client
    client = get_opensearch_client()

    # Fetch judgments
    logger.info(f"Fetching judgments from {judgments_index}")
    judgments = fetch_judgments(client, judgments_index)
    logger.info(f"Fetched {len(judgments)} judgments")

    if not judgments:
        return {
            "success": False,
            "message": "No judgments found",
            "recordCount": 0
        }

    # Extract features for each judgment
    feature_names = [
        "bm25_score",
        "title_match",
        "description_match",
        "category_match",
        "brand_match",
        "price_log",
        "popularity_score",
        "recency_score"
    ]

    training_data = []
    for i, judgment in enumerate(judgments):
        query = judgment['query']
        doc_id = judgment['doc_id']

        if not query or not doc_id:
            continue

        features = extract_features(client, query, doc_id, products_index)
        training_data.append({
            "query": query,
            "doc_id": doc_id,
            "rating": judgment['rating'],
            "features": features
        })

        if (i + 1) % 100 == 0:
            logger.info(f"Processed {i + 1}/{len(judgments)} judgments")

    logger.info(f"Prepared {len(training_data)} training records")

    # Format as RankLib
    ranklib_data = format_for_ranklib(training_data, feature_names)

    # Save to S3
    s3_uri = None
    if data_bucket:
        timestamp = datetime.utcnow().strftime('%Y%m%d_%H%M%S')
        key = f"ltr-training/training_data_{timestamp}.txt"
        s3_uri = save_to_s3(ranklib_data, data_bucket, key)
        logger.info(f"Saved training data to {s3_uri}")

    # Save feature definitions
    feature_config = {
        "name": "ubi_features",
        "features": [
            {"name": name, "index": i}
            for i, name in enumerate(feature_names, 1)
        ]
    }

    if data_bucket:
        feature_key = f"ltr-training/feature_config_{timestamp}.json"
        save_to_s3(json.dumps(feature_config, indent=2), data_bucket, feature_key)

    result = {
        "success": True,
        "recordCount": len(training_data),
        "featureCount": len(feature_names),
        "features": feature_names,
        "s3Uri": s3_uri,
        "timestamp": datetime.utcnow().isoformat()
    }

    logger.info(f"LTR data preparation complete: {json.dumps(result)}")
    return result

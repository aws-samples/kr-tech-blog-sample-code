"""
Lambda function to generate relevance judgments using Claude Sonnet 4.5.

This function:
1. Takes queries from the extract step
2. Searches for documents in the products index
3. Uses Claude Sonnet 4.5 via Bedrock to generate relevance judgments
4. Saves judgments to OpenSearch
"""

import json
import logging
import os
import time
from datetime import datetime
from typing import Any

import boto3
from opensearchpy import OpenSearch, RequestsHttpConnection, helpers
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


def get_bedrock_client():
    """Create Bedrock runtime client."""
    region = os.environ.get('AWS_REGION_NAME', 'us-east-1')
    return boto3.client('bedrock-runtime', region_name=region)


def search_documents(
    client: OpenSearch,
    query: str,
    index: str,
    top_k: int = 10
) -> list[dict[str, Any]]:
    """
    Search for documents matching the query.

    Args:
        client: OpenSearch client
        query: Search query
        index: Index to search
        top_k: Number of documents to return

    Returns:
        List of matching documents
    """
    search_fields = ["name^3", "description^2", "category", "brand", "tags"]

    search_body = {
        "size": top_k,
        "query": {
            "multi_match": {
                "query": query,
                "fields": search_fields,
                "type": "best_fields",
                "fuzziness": "AUTO"
            }
        }
    }

    try:
        response = client.search(index=index, body=search_body)
        hits = response['hits']['hits']

        documents = []
        for rank, hit in enumerate(hits, 1):
            doc = hit['_source']
            doc['_id'] = hit['_id']
            doc['_score'] = hit['_score']
            doc['_rank'] = rank
            documents.append(doc)

        return documents

    except Exception as e:
        logger.error(f"Error searching documents: {e}")
        return []


def create_judgment_prompt(query: str, document: dict[str, Any]) -> str:
    """Create a prompt for relevance judgment."""
    tags = document.get('tags', [])
    tags_str = ', '.join(tags) if tags else 'N/A'
    price = document.get('price', 0)
    price_str = f"{price:,}" if price else 'N/A'

    return f"""You are a search relevance expert evaluating e-commerce product search results.

Rate how relevant the following product is for the given search query.

## Search Query
"{query}"

## Product Information
- **Name**: {document.get('name', 'N/A')}
- **Category**: {document.get('category', 'N/A')}
- **Brand**: {document.get('brand', 'N/A')}
- **Description**: {document.get('description', 'N/A')}
- **Price**: {price_str}
- **Tags**: {tags_str}

## Rating Scale (0-4)
- **4 (Perfect)**: Exactly what the user is looking for. Direct match to query intent.
- **3 (Excellent)**: Highly relevant. Very good match, maybe slightly different variant.
- **2 (Good)**: Relevant. Related product that could satisfy the query.
- **1 (Fair)**: Marginally relevant. Loosely related, not ideal match.
- **0 (Poor)**: Not relevant. Unrelated to the query.

## Instructions
Respond with ONLY a valid JSON object in this exact format:
{{"rating": <0-4>, "reason": "<brief 1-sentence explanation>"}}"""


def get_llm_judgment(
    bedrock_client,
    model_id: str,
    query: str,
    document: dict[str, Any]
) -> dict[str, Any]:
    """
    Get relevance judgment from Claude.

    Args:
        bedrock_client: Bedrock runtime client
        model_id: Bedrock model ID
        query: Search query
        document: Document to judge

    Returns:
        Judgment result with rating and reason
    """
    prompt = create_judgment_prompt(query, document)

    try:
        response = bedrock_client.invoke_model(
            modelId=model_id,
            contentType='application/json',
            accept='application/json',
            body=json.dumps({
                "anthropic_version": "bedrock-2023-05-31",
                "max_tokens": 256,
                "temperature": 0.0,
                "messages": [
                    {"role": "user", "content": prompt}
                ]
            })
        )

        result = json.loads(response['body'].read())
        content = result['content'][0]['text']

        # Parse JSON response
        try:
            judgment = json.loads(content)
            rating = int(judgment.get('rating', 0))
            rating = max(0, min(4, rating))
            reason = judgment.get('reason', '')
        except json.JSONDecodeError:
            import re
            match = re.search(r'"rating"\s*:\s*(\d)', content)
            if match:
                rating = int(match.group(1))
                reason = content
            else:
                rating = -1
                reason = f"Failed to parse: {content[:100]}"

        return {
            "doc_id": document.get('_id', ''),
            "product_name": document.get('name', ''),
            "rank": document.get('_rank', 0),
            "rating": rating,
            "reason": reason
        }

    except Exception as e:
        logger.error(f"Error getting judgment: {e}")
        return {
            "doc_id": document.get('_id', ''),
            "product_name": document.get('name', ''),
            "rank": document.get('_rank', 0),
            "rating": -1,
            "reason": str(e)
        }


def save_judgments(
    client: OpenSearch,
    judgments: list[dict[str, Any]],
    index: str,
    model_id: str
) -> int:
    """
    Save judgments to OpenSearch.

    Args:
        client: OpenSearch client
        judgments: List of judgment records
        index: Target index
        model_id: Model ID used for judgments

    Returns:
        Number of successfully indexed documents
    """
    # Create index if not exists
    if not client.indices.exists(index=index):
        mapping = {
            "mappings": {
                "properties": {
                    "query": {"type": "text", "fields": {"keyword": {"type": "keyword"}}},
                    "doc_id": {"type": "keyword"},
                    "product_name": {"type": "text"},
                    "rank": {"type": "integer"},
                    "rating": {"type": "float"},
                    "reason": {"type": "text"},
                    "model": {"type": "keyword"},
                    "timestamp": {"type": "date"}
                }
            }
        }
        client.indices.create(index=index, body=mapping)
        logger.info(f"Created index: {index}")

    # Prepare bulk actions
    timestamp = datetime.utcnow().isoformat()
    actions = []

    for j in judgments:
        if j['rating'] >= 0:
            actions.append({
                "_index": index,
                "_source": {
                    **j,
                    "model": model_id,
                    "timestamp": timestamp
                }
            })

    if actions:
        success, failed = helpers.bulk(
            client, actions, raise_on_error=False
        )
        logger.info(f"Indexed {success} judgments, {len(failed) if failed else 0} failed")
        return success

    return 0


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """
    Lambda handler for judgment generation.

    Args:
        event: Lambda event containing:
            - queries: List of queries to judge (from extract step)
            - queryIds: List of query IDs (optional)
            - limit: Maximum queries to process (default: 10)

    Returns:
        Judgment generation results
    """
    logger.info(f"Starting judgment generation with event keys: {list(event.keys())}")

    # Get configuration
    model_id = os.environ.get('BEDROCK_MODEL_ID', 'us.anthropic.claude-sonnet-4-5-20250929-v1:0')
    products_index = os.environ.get('PRODUCTS_INDEX', 'products')
    judgments_index = os.environ.get('JUDGMENTS_INDEX', 'llm_judgments')
    top_k = int(os.environ.get('TOP_K_DOCS', '10'))
    rate_limit_delay = float(os.environ.get('RATE_LIMIT_DELAY', '0.5'))

    # Get queries from event
    queries = event.get('queries', [])
    limit = event.get('limit', 10)

    if not queries:
        # If no queries provided, try to get from extractResult
        extract_result = event.get('extractResult', {})
        queries = extract_result.get('queries', [])

    if not queries:
        logger.warning("No queries provided for judgment generation")
        return {
            "judgmentCount": 0,
            "message": "No queries to process"
        }

    # Limit queries to process
    queries_to_process = queries[:limit]
    logger.info(f"Processing {len(queries_to_process)} queries")

    # Initialize clients
    os_client = get_opensearch_client()
    bedrock_client = get_bedrock_client()

    all_judgments = []
    processed_queries = 0

    for query_data in queries_to_process:
        query_text = query_data.get('query') if isinstance(query_data, dict) else query_data

        if not query_text:
            continue

        logger.info(f"Processing query: '{query_text}'")

        # Search for documents
        documents = search_documents(os_client, query_text, products_index, top_k)

        if not documents:
            logger.warning(f"No documents found for query: {query_text}")
            continue

        # Generate judgments for each document
        for doc in documents:
            judgment = get_llm_judgment(bedrock_client, model_id, query_text, doc)
            judgment['query'] = query_text
            all_judgments.append(judgment)

            logger.info(
                f"  Rank {doc.get('_rank')}: {doc.get('name', 'N/A')[:30]}... "
                f"-> Rating: {judgment['rating']}"
            )

            # Rate limiting
            time.sleep(rate_limit_delay)

        processed_queries += 1

    # Save judgments
    saved_count = 0
    if all_judgments:
        saved_count = save_judgments(os_client, all_judgments, judgments_index, model_id)

    result = {
        "judgmentCount": len(all_judgments),
        "savedCount": saved_count,
        "processedQueries": processed_queries,
        "model": model_id,
        "timestamp": datetime.utcnow().isoformat()
    }

    logger.info(f"Judgment generation complete: {json.dumps(result)}")
    return result

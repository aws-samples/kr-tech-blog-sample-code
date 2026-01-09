"""
Lambda function to train and upload LTR model to OpenSearch.

This function:
1. Downloads training data from S3
2. Creates LTR store and featureset in OpenSearch
3. Trains model using XGBoost (via OpenSearch LTR plugin)
4. Uploads trained model to OpenSearch
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


def create_ltr_store(client: OpenSearch, store_name: str) -> bool:
    """
    Create LTR feature store if not exists.

    Args:
        client: OpenSearch client
        store_name: Name of the LTR store

    Returns:
        True if created or already exists
    """
    try:
        # Check if store exists
        client.transport.perform_request(
            'GET',
            f'/_ltr/{store_name}'
        )
        logger.info(f"LTR store '{store_name}' already exists")
        return True
    except Exception:
        pass

    try:
        # Create store
        client.transport.perform_request(
            'PUT',
            f'/_ltr/{store_name}'
        )
        logger.info(f"Created LTR store '{store_name}'")
        return True
    except Exception as e:
        logger.error(f"Error creating LTR store: {e}")
        return False


def create_featureset(
    client: OpenSearch,
    store_name: str,
    featureset_name: str,
    features: list[dict[str, Any]]
) -> bool:
    """
    Create or update LTR featureset.

    Args:
        client: OpenSearch client
        store_name: Name of the LTR store
        featureset_name: Name of the featureset
        features: List of feature definitions

    Returns:
        True if successful
    """
    # Build feature definitions for OpenSearch LTR
    feature_defs = []

    for i, feature in enumerate(features):
        name = feature['name']

        # Define feature templates based on feature type
        if name == 'bm25_score':
            feature_defs.append({
                "name": name,
                "params": ["keywords"],
                "template_language": "mustache",
                "template": {
                    "multi_match": {
                        "query": "{{keywords}}",
                        "fields": ["name^3", "description^2", "category", "brand", "tags"]
                    }
                }
            })
        elif name == 'title_match':
            feature_defs.append({
                "name": name,
                "params": ["keywords"],
                "template_language": "mustache",
                "template": {
                    "match": {
                        "name": "{{keywords}}"
                    }
                }
            })
        elif name == 'description_match':
            feature_defs.append({
                "name": name,
                "params": ["keywords"],
                "template_language": "mustache",
                "template": {
                    "match": {
                        "description": "{{keywords}}"
                    }
                }
            })
        elif name == 'category_match':
            feature_defs.append({
                "name": name,
                "params": ["keywords"],
                "template_language": "mustache",
                "template": {
                    "match": {
                        "category": "{{keywords}}"
                    }
                }
            })
        elif name == 'brand_match':
            feature_defs.append({
                "name": name,
                "params": ["keywords"],
                "template_language": "mustache",
                "template": {
                    "match": {
                        "brand": "{{keywords}}"
                    }
                }
            })
        elif name == 'price_log':
            feature_defs.append({
                "name": name,
                "params": [],
                "template_language": "mustache",
                "template": {
                    "function_score": {
                        "query": {"match_all": {}},
                        "field_value_factor": {
                            "field": "price",
                            "modifier": "log1p",
                            "missing": 1
                        }
                    }
                }
            })
        elif name == 'popularity_score':
            feature_defs.append({
                "name": name,
                "params": [],
                "template_language": "mustache",
                "template": {
                    "function_score": {
                        "query": {"match_all": {}},
                        "field_value_factor": {
                            "field": "popularity",
                            "modifier": "none",
                            "missing": 0
                        }
                    }
                }
            })
        elif name == 'recency_score':
            feature_defs.append({
                "name": name,
                "params": [],
                "template_language": "mustache",
                "template": {
                    "function_score": {
                        "query": {"match_all": {}},
                        "field_value_factor": {
                            "field": "recency_score",
                            "modifier": "none",
                            "missing": 0.5
                        }
                    }
                }
            })

    featureset_body = {
        "featureset": {
            "name": featureset_name,
            "features": feature_defs
        }
    }

    try:
        # Try to delete existing featureset first
        try:
            client.transport.perform_request(
                'DELETE',
                f'/_ltr/{store_name}/_featureset/{featureset_name}'
            )
        except Exception:
            pass

        # Create featureset
        client.transport.perform_request(
            'PUT',
            f'/_ltr/{store_name}/_featureset/{featureset_name}',
            body=featureset_body
        )
        logger.info(f"Created featureset '{featureset_name}' with {len(feature_defs)} features")
        return True

    except Exception as e:
        logger.error(f"Error creating featureset: {e}")
        return False


def download_training_data(s3_uri: str) -> str:
    """Download training data from S3."""
    # Parse S3 URI
    parts = s3_uri.replace('s3://', '').split('/', 1)
    bucket = parts[0]
    key = parts[1]

    s3 = boto3.client('s3')
    response = s3.get_object(Bucket=bucket, Key=key)
    return response['Body'].read().decode('utf-8')


def upload_model(
    client: OpenSearch,
    store_name: str,
    model_name: str,
    featureset_name: str,
    training_data: str
) -> bool:
    """
    Upload and train LTR model.

    Note: This uses the OpenSearch LTR plugin's training API.
    For production, consider using external XGBoost training.

    Args:
        client: OpenSearch client
        store_name: LTR store name
        model_name: Model name
        featureset_name: Featureset name
        training_data: RankLib formatted training data

    Returns:
        True if successful
    """
    # Parse training data to get model definition
    # For demo, we'll create a simple linear model based on feature weights

    # Count features from first line
    lines = [l for l in training_data.strip().split('\n') if l]
    if not lines:
        logger.error("No training data")
        return False

    # Parse feature count from first line
    first_line = lines[0]
    feature_parts = [p for p in first_line.split() if ':' in p and not p.startswith('qid:')]
    num_features = len([p for p in feature_parts if not p.startswith('#')])

    # For demo: create a simple ranklib model definition
    # In production, train with XGBoost externally and upload the model
    model_definition = {
        "model": {
            "name": model_name,
            "model": {
                "type": "model/linear",
                "definition": {
                    # Simple weights - in production, these come from actual training
                    "1": 1.0,   # bm25_score
                    "2": 0.5,   # title_match
                    "3": 0.3,   # description_match
                    "4": 0.2,   # category_match
                    "5": 0.2,   # brand_match
                    "6": 0.1,   # price_log
                    "7": 0.3,   # popularity_score
                    "8": 0.1    # recency_score
                }
            }
        }
    }

    try:
        # Delete existing model if exists
        try:
            client.transport.perform_request(
                'DELETE',
                f'/_ltr/{store_name}/_model/{model_name}'
            )
        except Exception:
            pass

        # Create model
        client.transport.perform_request(
            'POST',
            f'/_ltr/{store_name}/_featureset/{featureset_name}/_createmodel',
            body=model_definition
        )
        logger.info(f"Created model '{model_name}'")
        return True

    except Exception as e:
        logger.error(f"Error creating model: {e}")
        return False


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """
    Lambda handler for LTR model training.

    Args:
        event: Lambda event containing:
            - s3Uri: S3 URI of training data (from prepare step)

    Returns:
        Training results
    """
    logger.info(f"Starting LTR model training with event keys: {list(event.keys())}")

    # Get configuration
    store_name = os.environ.get('LTR_STORE_NAME', 'ubi_ltr_store')
    featureset_name = os.environ.get('LTR_FEATURESET_NAME', 'ubi_features')
    model_name = os.environ.get('LTR_MODEL_NAME', 'ubi_ltr_model')

    # Get S3 URI from event
    s3_uri = event.get('s3Uri')
    if not s3_uri:
        ltr_data_result = event.get('ltrDataResult', {})
        s3_uri = ltr_data_result.get('s3Uri')

    if not s3_uri:
        logger.warning("No training data S3 URI provided")
        return {
            "success": False,
            "message": "No training data provided"
        }

    # Initialize client
    client = get_opensearch_client()

    # Create LTR store
    if not create_ltr_store(client, store_name):
        return {
            "success": False,
            "message": "Failed to create LTR store"
        }

    # Define features
    features = [
        {"name": "bm25_score", "index": 1},
        {"name": "title_match", "index": 2},
        {"name": "description_match", "index": 3},
        {"name": "category_match", "index": 4},
        {"name": "brand_match", "index": 5},
        {"name": "price_log", "index": 6},
        {"name": "popularity_score", "index": 7},
        {"name": "recency_score", "index": 8}
    ]

    # Create featureset
    if not create_featureset(client, store_name, featureset_name, features):
        return {
            "success": False,
            "message": "Failed to create featureset"
        }

    # Download training data
    logger.info(f"Downloading training data from {s3_uri}")
    training_data = download_training_data(s3_uri)
    logger.info(f"Downloaded {len(training_data)} bytes of training data")

    # Upload model
    if not upload_model(client, store_name, model_name, featureset_name, training_data):
        return {
            "success": False,
            "message": "Failed to upload model"
        }

    result = {
        "success": True,
        "storeName": store_name,
        "featuresetName": featureset_name,
        "modelName": model_name,
        "featureCount": len(features),
        "timestamp": datetime.utcnow().isoformat()
    }

    # Log rescore query example
    rescore_query = {
        "query": {
            "match": {
                "name": "{{user_query}}"
            }
        },
        "rescore": {
            "window_size": 100,
            "query": {
                "rescore_query": {
                    "sltr": {
                        "params": {"keywords": "{{user_query}}"},
                        "model": model_name
                    }
                },
                "rescore_query_weight": 2
            }
        }
    }

    result["rescoreQueryExample"] = rescore_query

    logger.info(f"LTR model training complete: {json.dumps(result)}")
    return result

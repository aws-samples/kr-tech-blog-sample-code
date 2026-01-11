"""FastAPI backend for UBI sample web application.

Runs as AWS Lambda function with API Gateway.
Configuration via SSM Parameter Store.
Authentication via Secrets Manager (ID/password).
UBI data sent to unified OSI pipeline with SigV4 authentication.
"""
import os
import json
import boto3
import requests
from functools import lru_cache
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Any, Optional
from opensearchpy import OpenSearch, RequestsHttpConnection
from requests_aws4auth import AWS4Auth

# For Lambda compatibility
from mangum import Mangum

app = FastAPI(title="UBI Sample API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Environment configuration (set by Lambda environment variables)
ENV_PREFIX = os.environ.get("ENV_PREFIX", "dev")
# Note: AWS_REGION is a reserved Lambda env var, so we use AWS_REGION_NAME
AWS_REGION = os.environ.get("AWS_REGION_NAME", os.environ.get("AWS_REGION", "us-east-1"))


@lru_cache()
def get_ssm_parameter(param_name: str) -> str:
    """Get parameter from SSM Parameter Store with caching."""
    ssm = boto3.client("ssm", region_name=AWS_REGION)
    response = ssm.get_parameter(Name=param_name, WithDecryption=True)
    return response["Parameter"]["Value"]


@lru_cache()
def get_secret(secret_name: str) -> dict:
    """Get secret from Secrets Manager with caching."""
    sm = boto3.client("secretsmanager", region_name=AWS_REGION)
    response = sm.get_secret_value(SecretId=secret_name)
    return json.loads(response["SecretString"])


def get_config() -> dict:
    """Get OpenSearch configuration from SSM and Secrets Manager."""
    return {
        "host": get_ssm_parameter(f"/{ENV_PREFIX}/ubi-ltr/opensearch/host"),
        "region": get_ssm_parameter(f"/{ENV_PREFIX}/ubi-ltr/opensearch/region"),
        "index_name": get_ssm_parameter(f"/{ENV_PREFIX}/ubi-ltr/opensearch/index-name"),
    }


def get_osi_config() -> dict:
    """Get unified OSI pipeline endpoint from SSM Parameter Store."""
    try:
        return {
            "pipeline_endpoint": get_ssm_parameter(f"/{ENV_PREFIX}/ubi-ltr/osi/pipeline-endpoint"),
        }
    except Exception:
        # OSI not configured, fall back to direct OpenSearch
        return None


def get_aws4auth() -> AWS4Auth:
    """Get AWS SigV4 authentication for OSI endpoints."""
    session = boto3.Session(region_name=AWS_REGION)
    credentials = session.get_credentials()
    return AWS4Auth(
        credentials.access_key,
        credentials.secret_key,
        AWS_REGION,
        "osis",
        session_token=credentials.token,
    )


def get_credentials() -> tuple[str, str]:
    """Get OpenSearch credentials from Secrets Manager."""
    secret_name = f"{ENV_PREFIX}-ubi-opensearch-master-user"
    secret = get_secret(secret_name)
    return secret["username"], secret["password"]


def get_client() -> OpenSearch:
    """Create OpenSearch client with ID/password authentication."""
    config = get_config()
    username, password = get_credentials()

    return OpenSearch(
        hosts=[{"host": config["host"], "port": 443}],
        http_auth=(username, password),
        use_ssl=True,
        verify_certs=True,
        connection_class=RequestsHttpConnection,
    )


class SearchRequest(BaseModel):
    query: str
    size: int = 10
    query_id: Optional[str] = None


class UBIQuery(BaseModel):
    query_id: str
    user_query: str
    query_response_id: str
    application: str
    timestamp: str
    client_id: Optional[str] = None
    session_id: Optional[str] = None
    query_response_hit_ids: list[str] = []


class UBIEventPosition(BaseModel):
    ordinal: Optional[int] = None
    x: Optional[int] = None
    y: Optional[int] = None
    page_depth: Optional[int] = None
    scroll_depth: Optional[int] = None
    trail: Optional[str] = None


class UBIEventObjectDetail(BaseModel):
    price: Optional[float] = None
    margin: Optional[float] = None
    cost: Optional[float] = None
    supplier: Optional[str] = None
    isTrusted: Optional[bool] = None


class UBIEventObject(BaseModel):
    object_id: Optional[str] = None
    object_id_field: Optional[str] = None
    name: Optional[str] = None
    description: Optional[str] = None
    object_detail: Optional[UBIEventObjectDetail] = None


class UBIEventAttributes(BaseModel):
    session_id: Optional[str] = None
    browser: Optional[str] = None
    dwell_time: Optional[float] = None
    result_count: Optional[int] = None
    position: Optional[UBIEventPosition] = None
    object: Optional[UBIEventObject] = None


class UBIEvent(BaseModel):
    action_name: str
    query_id: str
    timestamp: int
    client_id: Optional[str] = None
    message: Optional[str] = None
    event_attributes: Optional[UBIEventAttributes] = None


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/api/search")
def search(req: SearchRequest):
    client = get_client()
    config = get_config()
    body = {
        "query": {
            "multi_match": {
                "query": req.query,
                "fields": ["name^2", "description", "brand", "category"],
            }
        },
        "size": req.size,
    }
    try:
        resp = client.search(index=config["index_name"], body=body)
        hits = resp.get("hits", {}).get("hits", [])
        return {
            "total": resp.get("hits", {}).get("total", {}).get("value", 0),
            "hits": [
                {
                    "id": h["_id"],
                    "score": h["_score"],
                    **h.get("_source", {}),
                }
                for h in hits
            ],
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


def send_to_osi(endpoint: str, data: list[dict]) -> dict:
    """Send data to unified OSI pipeline endpoint with SigV4 authentication.

    The pipeline uses routing based on the 'type' field in each document:
    - type: "query" -> routes to ubi_queries index
    - type: "event" -> routes to ubi_events index
    """
    auth = get_aws4auth()
    url = f"https://{endpoint}/ubi"

    headers = {"Content-Type": "application/json"}

    # OSI expects a JSON array of documents
    try:
        response = requests.post(
            url,
            json=data,  # Send as JSON array
            auth=auth,
            headers=headers,
            timeout=30,
        )
        if response.status_code in (200, 201):
            return {"success_count": len(data), "errors": []}
        else:
            return {"success_count": 0, "errors": [f"Status {response.status_code}: {response.text}"]}
    except Exception as e:
        return {"success_count": 0, "errors": [str(e)]}


@app.post("/api/ubi/queries")
def log_query(queries: list[UBIQuery]):
    """Send UBI queries to unified OSI pipeline or fall back to direct OpenSearch."""
    osi_config = get_osi_config()

    if osi_config:
        # Use unified OSI pipeline with type field for routing
        try:
            # Add type field for routing
            data = [{"type": "query", **q.model_dump()} for q in queries]
            result = send_to_osi(osi_config["pipeline_endpoint"], data)
            if result["errors"]:
                raise HTTPException(
                    status_code=500,
                    detail=f"OSI errors: {result['errors'][:3]}"  # Limit error details
                )
            return {"success": True, "count": result["success_count"], "method": "osi"}
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"OSI error: {str(e)}")
    else:
        # Fall back to direct OpenSearch
        client = get_client()
        try:
            for q in queries:
                client.index(index="ubi_queries", body=q.model_dump(), id=q.query_id)
            return {"success": True, "count": len(queries), "method": "direct"}
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/ubi/events")
def log_event(events: list[UBIEvent]):
    """Send UBI events to unified OSI pipeline or fall back to direct OpenSearch."""
    osi_config = get_osi_config()

    if osi_config:
        # Use unified OSI pipeline with type field for routing
        try:
            # Add type field for routing
            data = [{"type": "event", **e.model_dump()} for e in events]
            result = send_to_osi(osi_config["pipeline_endpoint"], data)
            if result["errors"]:
                raise HTTPException(
                    status_code=500,
                    detail=f"OSI errors: {result['errors'][:3]}"  # Limit error details
                )
            return {"success": True, "count": result["success_count"], "method": "osi"}
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"OSI error: {str(e)}")
    else:
        # Fall back to direct OpenSearch
        client = get_client()
        try:
            for e in events:
                client.index(index="ubi_events", body=e.model_dump())
            return {"success": True, "count": len(events), "method": "direct"}
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))


# Lambda handler
handler = Mangum(app)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)

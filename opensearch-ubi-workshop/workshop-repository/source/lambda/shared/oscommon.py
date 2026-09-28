"""Shared helpers for the ecom-ubi Lambdas (copied into each function by build.sh)."""
import json
import os
import re

import boto3
from opensearchpy import OpenSearch, RequestsHttpConnection
from requests_aws4auth import AWS4Auth

REGION = os.environ.get("AWS_REGION", "us-east-1")

_client = None


def os_client() -> OpenSearch:
    global _client
    if _client is None:
        endpoint = os.environ["OPENSEARCH_ENDPOINT"]
        creds = boto3.Session().get_credentials()
        auth = AWS4Auth(
            creds.access_key, creds.secret_key, REGION, "es", session_token=creds.token
        )
        _client = OpenSearch(
            hosts=[{"host": endpoint, "port": 443}],
            http_auth=auth,
            use_ssl=True,
            verify_certs=True,
            connection_class=RequestsHttpConnection,
            timeout=60,
            max_retries=2,
            retry_on_timeout=True,
        )
    return _client


def norm_query(q: str) -> str:
    """Normalize a user query for grouping (lowercase, collapse whitespace)."""
    return re.sub(r"\s+", " ", (q or "").strip().lower())


def s3_put_json(bucket: str, key: str, obj) -> str:
    boto3.client("s3").put_object(
        Bucket=bucket,
        Key=key,
        Body=json.dumps(obj, ensure_ascii=False, default=str).encode("utf-8"),
        ContentType="application/json",
    )
    return f"s3://{bucket}/{key}"


def s3_get_json(bucket: str, key: str):
    body = boto3.client("s3").get_object(Bucket=bucket, Key=key)["Body"].read()
    return json.loads(body)


def s3_put_text(bucket: str, key: str, text: str) -> str:
    boto3.client("s3").put_object(
        Bucket=bucket, Key=key, Body=text.encode("utf-8"), ContentType="text/plain"
    )
    return f"s3://{bucket}/{key}"


def s3_get_text(bucket: str, key: str) -> str:
    return boto3.client("s3").get_object(Bucket=bucket, Key=key)["Body"].read().decode("utf-8")


def scroll_all(client: OpenSearch, index: str, body: dict, limit: int = 200000):
    """Yield all hits for a query using the scroll API (bounded by limit)."""
    body = dict(body)
    body.setdefault("size", 1000)
    try:
        resp = client.search(index=index, body=body, scroll="2m")
    except Exception:
        return
    sid = resp.get("_scroll_id")
    fetched = 0
    try:
        while True:
            hits = resp["hits"]["hits"]
            if not hits:
                break
            for h in hits:
                yield h
                fetched += 1
                if fetched >= limit:
                    return
            resp = client.scroll(scroll_id=sid, scroll="2m")
            sid = resp.get("_scroll_id")
    finally:
        try:
            client.clear_scroll(scroll_id=sid)
        except Exception:
            pass

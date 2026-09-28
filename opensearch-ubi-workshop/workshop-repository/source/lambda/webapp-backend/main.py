"""VoltMall storefront API (FastAPI on Lambda).

- /api/search       : product search (BM25 baseline, optional LTR rescoring),
                      logs a UBI query record to the OSI pipeline per search
- /api/ubi/events   : forwards client UBI events to the OSI pipeline (SigV4)
- /api/products/... : product detail
- /api/categories   : facets for the storefront UI
"""
import json
import logging
import os
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

import boto3
import requests
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from mangum import Mangum
from opensearchpy import OpenSearch, RequestsHttpConnection
from pydantic import BaseModel, ConfigDict, Field
from requests_aws4auth import AWS4Auth

logger = logging.getLogger()
logger.setLevel("INFO")

REGION = os.environ.get("AWS_REGION", "us-east-1")
OPENSEARCH_ENDPOINT = os.environ["OPENSEARCH_ENDPOINT"]
OSI_INGEST_URL = os.environ.get("OSI_INGEST_URL", "")
PRODUCTS_INDEX = os.environ.get("PRODUCTS_INDEX", "ecom_products")
LTR_STORE = os.environ.get("LTR_STORE", "_default_")
LTR_FEATURESET = os.environ.get("LTR_FEATURESET", "ecom_features")
LTR_MODEL_PARAM = os.environ.get("LTR_MODEL_PARAM", "/ecom-ubi/ltr/model-name")
APPLICATION = os.environ.get("APPLICATION", "voltmall")

SEARCH_FIELDS = ["name^3", "series^2", "brand^1.5", "category^1.5", "model_no", "description", "tags"]
# Must match evaluate_model.py so the blend that was measured/promoted is the
# one actually served (no eval/serve skew).
LTR_RESCORE_WEIGHT = float(os.environ.get("LTR_RESCORE_WEIGHT", "1.5"))

app = FastAPI(title="VoltMall API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

_os_client: Optional[OpenSearch] = None
_model_cache: dict = {"name": None, "ts": 0.0}


def os_client() -> OpenSearch:
    global _os_client
    if _os_client is None:
        creds = boto3.Session().get_credentials()
        auth = AWS4Auth(creds.access_key, creds.secret_key, REGION, "es", session_token=creds.token)
        _os_client = OpenSearch(
            hosts=[{"host": OPENSEARCH_ENDPOINT, "port": 443}],
            http_auth=auth,
            use_ssl=True,
            verify_certs=True,
            connection_class=RequestsHttpConnection,
            timeout=20,
        )
    return _os_client


def osi_auth() -> AWS4Auth:
    creds = boto3.Session().get_credentials()
    return AWS4Auth(creds.access_key, creds.secret_key, REGION, "osis", session_token=creds.token)


def ltr_model_name() -> Optional[str]:
    """Currently promoted LTR model name from SSM (cached 60s). None = no model yet."""
    now = time.time()
    if now - _model_cache["ts"] < 60:
        return _model_cache["name"]
    name = None
    try:
        resp = boto3.client("ssm", region_name=REGION).get_parameter(Name=LTR_MODEL_PARAM)
        value = resp["Parameter"]["Value"].strip()
        name = value if value and value != "none" else None
    except Exception:
        name = None
    _model_cache.update(name=name, ts=now)
    return name


def send_to_osi(records: list[dict]) -> bool:
    if not OSI_INGEST_URL or not records:
        return False
    try:
        resp = requests.post(
            OSI_INGEST_URL,
            json=records,
            auth=osi_auth(),
            headers={"content-type": "application/json"},
            timeout=5,
        )
        if resp.status_code not in (200, 201):
            logger.warning("OSI ingest failed %s: %s", resp.status_code, resp.text[:300])
            return False
        return True
    except Exception as e:
        logger.warning("OSI ingest error: %s", e)
        return False


class SearchRequest(BaseModel):
    model_config = ConfigDict(extra="allow")
    query: str = ""
    size: int = Field(default=24, ge=1, le=100)
    from_: int = Field(default=0, alias="from", ge=0)
    category: Optional[str] = None
    brand: Optional[str] = None
    price_min: Optional[int] = None
    price_max: Optional[int] = None
    sort: str = "relevance"  # relevance | price_asc | price_desc | popularity | rating
    use_ltr: bool = False
    client_id: Optional[str] = None
    session_id: Optional[str] = None


class UbiEvent(BaseModel):
    model_config = ConfigDict(extra="allow")
    action_name: str
    query_id: Optional[str] = None
    client_id: Optional[str] = None
    session_id: Optional[str] = None
    timestamp: Optional[int] = None
    message: Optional[str] = None
    event_attributes: Optional[dict] = None


def build_search_body(req: SearchRequest) -> dict:
    filters: list[dict] = []
    if req.category:
        filters.append({"term": {"category.keyword": req.category}})
    if req.brand:
        filters.append({"term": {"brand.keyword": req.brand}})
    price_range: dict[str, Any] = {}
    if req.price_min is not None:
        price_range["gte"] = req.price_min
    if req.price_max is not None:
        price_range["lte"] = req.price_max
    if price_range:
        filters.append({"range": {"price": price_range}})

    if req.query.strip():
        base_query: dict = {
            "multi_match": {
                "query": req.query,
                "fields": SEARCH_FIELDS,
                "type": "best_fields",
                "operator": "or",
            }
        }
    else:
        base_query = {"match_all": {}}

    body: dict = {
        "query": {"bool": {"must": [base_query], "filter": filters}},
        "size": req.size,
        "from": req.from_,
        "track_total_hits": True,
        # never ship the 1024-dim embedding / its source text to the browser
        "_source": {"excludes": ["name_embedding", "embed_source"]},
    }

    if not req.query.strip():
        body["sort"] = [{"popularity": "desc"}, {"review_count": "desc"}]
    elif req.sort == "price_asc":
        body["sort"] = [{"price": "asc"}]
    elif req.sort == "price_desc":
        body["sort"] = [{"price": "desc"}]
    elif req.sort == "popularity":
        body["sort"] = [{"popularity": "desc"}]
    elif req.sort == "rating":
        body["sort"] = [{"rating": "desc"}]
    return body


def apply_ltr_rescore(body: dict, keywords: str, model: str) -> dict:
    sltr: dict = {
        "params": {"keywords": keywords},
        "model": model,
    }
    if LTR_STORE not in ("", "_default_"):
        sltr["store"] = LTR_STORE
    body = dict(body)
    # blend: keep the BM25 base score and add the LTR score on top — measured
    # better live nDCG than full score replacement (unjudged/lexical sanity)
    body["rescore"] = {
        "window_size": 100,
        "query": {
            "rescore_query": {"sltr": sltr},
            "query_weight": 1.0,
            "rescore_query_weight": LTR_RESCORE_WEIGHT,
            "score_mode": "total",
        },
    }
    return body


@app.get("/health")
def health():
    return {"status": "ok", "app": APPLICATION}


@app.get("/api/config")
def config():
    return {
        "application": APPLICATION,
        "products_index": PRODUCTS_INDEX,
        "ltr_model": ltr_model_name(),
        "osi_enabled": bool(OSI_INGEST_URL),
    }


@app.get("/api/categories")
def categories():
    body = {
        "size": 0,
        "aggs": {
            "categories": {"terms": {"field": "category.keyword", "size": 30}},
            "brands": {"terms": {"field": "brand.keyword", "size": 40}},
        },
    }
    try:
        resp = os_client().search(index=PRODUCTS_INDEX, body=body)
        return {
            "categories": [b["key"] for b in resp["aggregations"]["categories"]["buckets"]],
            "brands": [b["key"] for b in resp["aggregations"]["brands"]["buckets"]],
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/products/{product_id}")
def product_detail(product_id: str):
    try:
        doc = os_client().get(index=PRODUCTS_INDEX, id=product_id,
                              _source_excludes=["name_embedding", "embed_source"])
        return {"id": doc["_id"], **doc["_source"]}
    except Exception:
        raise HTTPException(status_code=404, detail="product not found")


@app.post("/api/search")
def search(req: SearchRequest):
    started = time.time()
    query_text = req.query.strip()
    body = build_search_body(req)

    ltr_used = False
    model = ltr_model_name() if (req.use_ltr and query_text and req.sort == "relevance") else None
    client = os_client()

    resp = None
    if model:
        try:
            resp = client.search(index=PRODUCTS_INDEX, body=apply_ltr_rescore(body, query_text, model))
            ltr_used = True
        except Exception as e:
            logger.warning("LTR rescore failed (%s), falling back to baseline", str(e)[:200])
    if resp is None:
        try:
            resp = client.search(index=PRODUCTS_INDEX, body=body)
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e)[:300])

    hits = resp.get("hits", {}).get("hits", [])
    hit_ids = [h["_id"] for h in hits]
    results = [
        {"id": h["_id"], "score": h.get("_score"), "position": req.from_ + i, **h.get("_source", {})}
        for i, h in enumerate(hits)
    ]

    query_id = str(uuid.uuid4())
    ubi_logged = False
    if query_text:
        ubi_query = {
            "type": "query",
            "application": APPLICATION,
            "query_id": query_id,
            "client_id": req.client_id or "unknown",
            "session_id": req.session_id,
            "user_query": query_text,
            "query": json.dumps(body, ensure_ascii=False),
            "query_attributes": {
                "category": req.category,
                "brand": req.brand,
                "sort": req.sort,
                "ltr_used": ltr_used,
                "ltr_model": model if ltr_used else None,
                "from": req.from_,
                "size": req.size,
            },
            "query_response_id": str(uuid.uuid4()),
            "query_response_hit_ids": hit_ids,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        ubi_logged = send_to_osi([ubi_query])

    return {
        "query_id": query_id,
        "total": resp.get("hits", {}).get("total", {}).get("value", 0),
        "took_ms": int((time.time() - started) * 1000),
        "ltr_used": ltr_used,
        "ltr_model": model if ltr_used else None,
        "ubi_logged": ubi_logged,
        "hits": results,
    }


@app.post("/api/ubi/events")
def ubi_events(events: list[UbiEvent]):
    if not events:
        return {"accepted": 0}
    if len(events) > 200:
        raise HTTPException(status_code=413, detail="too many events in one batch (max 200)")
    now_ms = int(time.time() * 1000)
    records = []
    for e in events:
        rec = e.model_dump(exclude_none=True)
        rec["type"] = "event"
        rec.setdefault("application", APPLICATION)
        rec.setdefault("timestamp", now_ms)
        records.append(rec)
    ok = send_to_osi(records)
    if not ok:
        raise HTTPException(status_code=502, detail="failed to forward events to OSI")
    return {"accepted": len(records)}


handler = Mangum(app)

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)

"""FastAPI 엔트리포인트 — LangGraph 멀티 에이전트 워크플로우 API"""

from fastapi import FastAPI
from pydantic import BaseModel
from typing import Optional

from app.workflow import build_workflow
from app.tracing import observe, propagate_attributes, get_langfuse_client

app = FastAPI(title="Agentic AI Support", version="1.0.0")
workflow = build_workflow()


class QueryRequest(BaseModel):
    query: str


class QueryResponse(BaseModel):
    user_query: str
    query_type: Optional[str]
    selected_model: Optional[str]
    response: Optional[str]
    evaluation_score: Optional[float]


@app.get("/health")
def health():
    return {"status": "ok"}


@observe(name="customer_support")
def run_workflow(query: str) -> dict:
    """워크플로우 실행 — @observe로 Langfuse span 자동 기록"""
    return workflow.invoke({
        "user_query": query,
        "query_type": None,
        "selected_model": None,
        "context": None,
        "response": None,
        "evaluation_score": None,
        "cost": None,
    })


@app.post("/query", response_model=QueryResponse)
def handle_query(req: QueryRequest):
    with propagate_attributes(
        trace_name="customer_support",
        tags=["eks-demo", "support"],
        metadata={"product": "aws-support"},
    ):
        result = run_workflow(req.query)

    return QueryResponse(
        user_query=result["user_query"],
        query_type=result.get("query_type"),
        selected_model=result.get("selected_model"),
        response=result.get("response"),
        evaluation_score=result.get("evaluation_score"),
    )


@app.on_event("shutdown")
def shutdown():
    client = get_langfuse_client()
    if client:
        client.flush()
        client.shutdown()

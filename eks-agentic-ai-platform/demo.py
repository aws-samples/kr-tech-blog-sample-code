#!/usr/bin/env python3
"""
데모 스크립트: LangGraph 멀티 에이전트 워크플로우 + Langfuse 트레이싱

사전 준비:
    kubectl port-forward svc/vllm 8000:8000 -n ai-inference &
    kubectl port-forward svc/langfuse-web 3000:3000 -n observability &

    pip install langchain_openai langgraph langfuse

실행:
    export LANGFUSE_SECRET_KEY="sk-lf-..."
    export LANGFUSE_PUBLIC_KEY="pk-lf-..."
    export LANGFUSE_BASE_URL="http://localhost:3000"
    python demo.py
"""

import json
import os
import time

from dotenv import load_dotenv
load_dotenv()  # .env 파일에서 환경변수 자동 로드

# OTLP exporter 타임아웃 늘리기 (port-forward 환경에서 기본값이 너무 짧음)
os.environ.setdefault("OTEL_EXPORTER_OTLP_TIMEOUT", "30000")
os.environ.setdefault("LANGFUSE_TIMEOUT", "30")

from langchain_openai import ChatOpenAI
from langgraph.graph import StateGraph, END
from typing import Optional
from typing_extensions import TypedDict


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

VLLM_URL = os.getenv("VLLM_URL", "http://localhost:8000/v1")
LANGFUSE_SECRET_KEY = os.getenv("LANGFUSE_SECRET_KEY", "")
LANGFUSE_PUBLIC_KEY = os.getenv("LANGFUSE_PUBLIC_KEY", "")
LANGFUSE_HOST = os.getenv("LANGFUSE_BASE_URL", "http://localhost:3000")
MODEL_NAME = "qwen3-8b"

LANGFUSE_ENABLED = bool(LANGFUSE_SECRET_KEY and LANGFUSE_PUBLIC_KEY)

# ---------------------------------------------------------------------------
# Langfuse v4 (OpenTelemetry 기반)
# ---------------------------------------------------------------------------

if LANGFUSE_ENABLED:
    from langfuse import Langfuse, observe, propagate_attributes

    langfuse_client = Langfuse(
        secret_key=LANGFUSE_SECRET_KEY,
        public_key=LANGFUSE_PUBLIC_KEY,
        host=LANGFUSE_HOST,
    )
else:
    langfuse_client = None

    def observe(*args, **kwargs):
        def decorator(fn):
            return fn
        if args and callable(args[0]):
            return args[0]
        return decorator

    from contextlib import contextmanager

    @contextmanager
    def propagate_attributes(**kwargs):
        yield


# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------

class SupportState(TypedDict):
    user_query: str
    query_type: Optional[str]
    selected_model: Optional[str]
    context: Optional[str]
    response: Optional[str]
    evaluation_score: Optional[float]


# ---------------------------------------------------------------------------
# LLM helper
# ---------------------------------------------------------------------------

def _llm() -> ChatOpenAI:
    return ChatOpenAI(base_url=VLLM_URL, api_key="dummy", model=MODEL_NAME)


# ---------------------------------------------------------------------------
# Agents
# ---------------------------------------------------------------------------

@observe(name="orchestrator")
def classify_query(state: SupportState) -> SupportState:
    """Orchestrator: 쿼리 유형 분류"""
    prompt = (
        "/no_think\n"
        "You are a query classifier. Classify the following query into "
        "exactly one category. Respond with ONLY one word: simple, complex, or document.\n\n"
        f"Query: {state['user_query']}"
    )
    result = _llm().invoke(prompt)

    # Remove <think> tags from Qwen3 responses
    import re
    raw = result.content.strip().lower()
    raw = re.sub(r'<think>.*?</think>', '', raw, flags=re.DOTALL).strip()
    query_type = raw.split()[0] if raw.split() else "simple"

    if query_type not in ("simple", "complex", "document"):
        query_type = "simple"

    model_map = {"simple": "qwen3-8b", "complex": "claude-3-sonnet", "document": "gpt-4o"}
    return {**state, "query_type": query_type, "selected_model": model_map[query_type]}


@observe(name="rag_agent")
def rag_respond(state: SupportState) -> SupportState:
    """RAG Agent: 지식 기반 응답 생성"""
    prompt = (
        f"/no_think\nYou are a helpful AWS support assistant. "
        f"Answer the following question clearly and concisely in Korean.\n\n"
        f"Question: {state['user_query']}"
    )
    result = _llm().invoke(prompt)
    return {**state, "context": "AWS documentation", "response": result.content}


@observe(name="document_agent")
def document_respond(state: SupportState) -> SupportState:
    """Document Agent: 문서 분석 응답"""
    prompt = (
        f"/no_think\nYou are an AWS document analysis assistant. "
        f"Analyze the following request and respond in Korean.\n\n"
        f"Request: {state['user_query']}"
    )
    result = _llm().invoke(prompt)
    return {**state, "response": result.content}


@observe(name="evaluation_agent")
def evaluate_response(state: SupportState) -> SupportState:
    """Evaluation Agent: 응답 품질 평가"""
    prompt = (
        f"/no_think\nEvaluate the following response to the user query on a scale of 0-10.\n"
        f"Score criteria: accuracy (0-4), completeness (0-3), friendliness (0-3).\n"
        f"Respond with ONLY a JSON object: {{\"accuracy\": N, \"completeness\": N, \"friendliness\": N}}\n\n"
        f"Query: {state['user_query']}\n"
        f"Response: {state.get('response', '')}"
    )
    result = _llm().invoke(prompt)
    try:
        scores = json.loads(result.content.strip())
        total = min(4, scores.get("accuracy", 0)) + min(3, scores.get("completeness", 0)) + min(3, scores.get("friendliness", 0))
    except (json.JSONDecodeError, ValueError):
        total = 7.0
    return {**state, "evaluation_score": float(total)}


# ---------------------------------------------------------------------------
# Workflow
# ---------------------------------------------------------------------------

def route_by_type(state: SupportState) -> str:
    if state.get("query_type") == "document":
        return "document_agent"
    return "rag_agent"


def build_workflow():
    graph = StateGraph(SupportState)
    graph.add_node("orchestrator", classify_query)
    graph.add_node("rag_agent", rag_respond)
    graph.add_node("document_agent", document_respond)
    graph.add_node("evaluation", evaluate_response)

    graph.set_entry_point("orchestrator")
    graph.add_conditional_edges(
        "orchestrator", route_by_type,
        {"rag_agent": "rag_agent", "document_agent": "document_agent"},
    )
    graph.add_edge("rag_agent", "evaluation")
    graph.add_edge("document_agent", "evaluation")
    graph.add_edge("evaluation", END)
    return graph.compile()


# ---------------------------------------------------------------------------
# Run with tracing
# ---------------------------------------------------------------------------

@observe(name="customer_support")
def run_single_query(workflow, query: str):
    """단일 쿼리 실행"""
    start = time.time()
    result = workflow.invoke({
        "user_query": query,
        "query_type": None,
        "selected_model": None,
        "context": None,
        "response": None,
        "evaluation_score": None,
    })
    duration = time.time() - start
    return result, duration


def run_with_tracing(workflow, query: str):
    """propagate_attributes로 트레이스 메타데이터 전파"""
    with propagate_attributes(
        trace_name="customer_support",
        tags=["demo", "support"],
        metadata={"product": "aws-support"},
    ):
        return run_single_query(workflow, query)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

DEMO_QUERIES = [
    ("S3 버킷 생성 방법을 알려주세요", "simple"),
    ("EKS 클러스터에서 OOM 에러가 발생할 때 트러블슈팅 방법", "complex"),
    ("AWS 청구서를 분석해주세요", "document"),
]


def main():
    print("=" * 70)
    print("🤖 Agentic AI Platform Demo — LangGraph + vLLM + Langfuse")
    print("=" * 70)

    if LANGFUSE_ENABLED:
        print(f"   Langfuse 트레이싱: ✅ ({LANGFUSE_HOST})")
    else:
        print("   Langfuse 트레이싱: ⚠️  키 미설정 — 트레이싱 건너뜀")

    workflow = build_workflow()

    for query, expected_type in DEMO_QUERIES:
        print(f"\n{'─' * 70}")
        print(f"📝 문의: {query}")
        print(f"   (예상 유형: {expected_type})")
        print(f"{'─' * 70}")

        result, duration = run_with_tracing(workflow, query)

        print(f"   분류: {result.get('query_type')}")
        print(f"   모델: {result.get('selected_model')}")
        print(f"   평가: {result.get('evaluation_score')}/10")
        print(f"   시간: {duration:.1f}s")
        print(f"\n   응답:")
        response = result.get("response", "")
        for line in response[:300].split("\n"):
            print(f"   {line}")
        if len(response) > 300:
            print(f"   ... (총 {len(response)}자)")

    if langfuse_client:
        langfuse_client.flush()
        langfuse_client.shutdown()
        print(f"\n{'=' * 70}")
        print(f"✅ Langfuse 트레이스 기록 완료!")
        print(f"   대시보드: {LANGFUSE_HOST}")
        print(f"{'=' * 70}")


if __name__ == "__main__":
    main()

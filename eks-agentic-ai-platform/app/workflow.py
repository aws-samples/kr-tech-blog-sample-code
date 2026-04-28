from langgraph.graph import StateGraph, END
from app.state import SupportState
from app.agents.orchestrator import classify_query
from app.agents.rag_agent import rag_respond
from app.agents.document_agent import document_respond
from app.agents.evaluation_agent import evaluate_response


def route_by_type(state: SupportState) -> str:
    """Route to the appropriate agent based on query classification."""
    if state.get("query_type") == "document":
        return "document_agent"
    return "rag_agent"


def build_workflow() -> StateGraph:
    """Build and compile the LangGraph workflow."""
    graph = StateGraph(SupportState)

    # Add nodes
    graph.add_node("orchestrator", classify_query)
    graph.add_node("rag_agent", rag_respond)
    graph.add_node("document_agent", document_respond)
    graph.add_node("evaluation", evaluate_response)

    # Set entry point
    graph.set_entry_point("orchestrator")

    # Add conditional routing
    graph.add_conditional_edges(
        "orchestrator",
        route_by_type,
        {"rag_agent": "rag_agent", "document_agent": "document_agent"},
    )

    # Both agents feed into evaluation
    graph.add_edge("rag_agent", "evaluation")
    graph.add_edge("document_agent", "evaluation")
    graph.add_edge("evaluation", END)

    return graph.compile()


# Pre-built workflow instance
workflow = build_workflow()

from langchain_openai import ChatOpenAI
from app.config import BIFROST_ENDPOINT, BIFROST_API_KEY
from app.state import SupportState
from app.tracing import observe


RAG_PROMPT = """You are an AWS service support assistant.
Use the following context to answer the user's question accurately and helpfully.

Context: {context}

User query: {query}

Provide a clear, helpful response about AWS services."""


def retrieve_context(query: str) -> str:
    """Retrieve context from AWS knowledge base (stub)."""
    return f"AWS documentation context for: {query}"


@observe(name="rag_agent")
def rag_respond(state: SupportState) -> SupportState:
    """Generate a response using RAG with the selected model."""
    context = retrieve_context(state["user_query"])

    llm = ChatOpenAI(
        base_url=BIFROST_ENDPOINT,
        api_key=BIFROST_API_KEY,
        model=state["selected_model"],
    )

    result = llm.invoke(
        RAG_PROMPT.format(context=context, query=state["user_query"])
    )

    return {
        **state,
        "context": context,
        "response": result.content,
    }

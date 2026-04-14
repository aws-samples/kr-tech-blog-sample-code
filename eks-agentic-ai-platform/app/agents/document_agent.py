from langchain_openai import ChatOpenAI
from app.config import BIFROST_ENDPOINT, BIFROST_API_KEY, MODEL_DOCUMENT
from app.state import SupportState
from app.tracing import observe


DOCUMENT_PROMPT = """You are an AWS document analysis assistant.
Analyze the following document-related request and provide a detailed response.
Focus on AWS billing, cost analysis, and document processing.

User query: {query}

Provide a thorough analysis."""


@observe(name="document_agent")
def document_respond(state: SupportState) -> SupportState:
    """Process document analysis requests using gpt-4o via Bifrost."""
    llm = ChatOpenAI(
        base_url=BIFROST_ENDPOINT,
        api_key=BIFROST_API_KEY,
        model=MODEL_DOCUMENT,
    )

    result = llm.invoke(
        DOCUMENT_PROMPT.format(query=state["user_query"])
    )

    return {
        **state,
        "response": result.content,
    }

from langchain_openai import ChatOpenAI
from app.config import BIFROST_ENDPOINT, BIFROST_API_KEY, CLASSIFICATION_MODEL_MAP, MODEL_CLASSIFIER
from app.state import SupportState
from app.tracing import observe


CLASSIFICATION_PROMPT = """You are a query classifier for an AWS service support system.
Classify the following user query into exactly one category:
- "simple": Basic AWS service questions (e.g., how to create a resource)
- "complex": Troubleshooting, debugging, or multi-step AWS problems
- "document": Document analysis requests (e.g., billing, cost reports)

Respond with ONLY one word: simple, complex, or document.

User query: {query}"""


@observe(name="orchestrator")
def classify_query(state: SupportState) -> SupportState:
    """Classify user query and select the appropriate model."""
    llm = ChatOpenAI(
        base_url=BIFROST_ENDPOINT,
        api_key=BIFROST_API_KEY,
        model=MODEL_CLASSIFIER,
    )

    result = llm.invoke(
        CLASSIFICATION_PROMPT.format(query=state["user_query"])
    )
    query_type = result.content.strip().lower()

    # Ensure valid classification
    if query_type not in CLASSIFICATION_MODEL_MAP:
        query_type = "complex"

    selected_model = CLASSIFICATION_MODEL_MAP[query_type]

    return {
        **state,
        "query_type": query_type,
        "selected_model": selected_model,
    }

import json
from langchain_openai import ChatOpenAI
from app.config import BIFROST_ENDPOINT, BIFROST_API_KEY, MODEL_EVALUATOR
from app.state import SupportState
from app.tracing import observe


EVALUATION_PROMPT = """/no_think
You are a response quality evaluator for an AWS support system.
Evaluate the following response to the user's query.

User query: {query}
Response: {response}

Score the response on three criteria:
- accuracy (0-4): Information correctness
- completeness (0-3): Coverage of all query aspects
- friendliness (0-3): Appropriate tone

Respond in JSON format only:
{{"accuracy": <int>, "completeness": <int>, "friendliness": <int>}}"""


@observe(name="evaluation_agent")
def evaluate_response(state: SupportState) -> SupportState:
    """Score the response on accuracy, completeness, and friendliness."""
    llm = ChatOpenAI(
        base_url=BIFROST_ENDPOINT,
        api_key=BIFROST_API_KEY,
        model=MODEL_EVALUATOR,
    )

    result = llm.invoke(
        EVALUATION_PROMPT.format(
            query=state["user_query"],
            response=state.get("response", ""),
        )
    )

    try:
        scores = json.loads(result.content)
        accuracy = max(0, min(4, int(scores.get("accuracy", 0))))
        completeness = max(0, min(3, int(scores.get("completeness", 0))))
        friendliness = max(0, min(3, int(scores.get("friendliness", 0))))
        total = accuracy + completeness + friendliness
    except (json.JSONDecodeError, ValueError, TypeError):
        total = 0.0

    return {
        **state,
        "evaluation_score": float(total),
    }

from typing import Optional
from typing_extensions import TypedDict


class SupportState(TypedDict):
    user_query: str
    query_type: Optional[str]       # "simple" | "complex" | "document"
    selected_model: Optional[str]   # "qwen3-8b" | "claude-3-sonnet" | "gpt-4o"
    context: Optional[str]
    response: Optional[str]
    evaluation_score: Optional[float]
    cost: Optional[float]

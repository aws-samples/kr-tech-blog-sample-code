import os

# Bifrost Gateway
BIFROST_ENDPOINT = os.getenv(
    "BIFROST_ENDPOINT",
    "http://bifrost.ai-inference.svc.cluster.local:8080/v1",
)
BIFROST_API_KEY = os.getenv("BIFROST_API_KEY", "test-1234")

# Model names (환경변수로 오버라이드 가능)
MODEL_SIMPLE = os.getenv("MODEL_SIMPLE", "qwen3-8b")
MODEL_COMPLEX = os.getenv("MODEL_COMPLEX", "anthropic.claude-3-sonnet")
MODEL_DOCUMENT = os.getenv("MODEL_DOCUMENT", "gpt-4o")
MODEL_CLASSIFIER = os.getenv("MODEL_CLASSIFIER", "gpt-4o")
MODEL_EVALUATOR = os.getenv("MODEL_EVALUATOR", "gpt-4o")

# Classification-to-model mapping
CLASSIFICATION_MODEL_MAP = {
    "simple": MODEL_SIMPLE,
    "complex": MODEL_COMPLEX,
    "document": MODEL_DOCUMENT,
}

# Langfuse
LANGFUSE_SECRET_KEY = os.getenv("LANGFUSE_SECRET_KEY", "")
LANGFUSE_PUBLIC_KEY = os.getenv("LANGFUSE_PUBLIC_KEY", "")
LANGFUSE_HOST = os.getenv(
    "LANGFUSE_HOST",
    "http://langfuse.observability.svc.cluster.local:3000",
)

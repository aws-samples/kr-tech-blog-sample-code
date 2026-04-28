import os

from dotenv import load_dotenv

load_dotenv()

# Bifrost Gateway
BIFROST_ENDPOINT = os.getenv("BIFROST_ENDPOINT")
BIFROST_API_KEY = os.getenv("BIFROST_API_KEY")

# Model names
MODEL_SIMPLE = os.getenv("MODEL_SIMPLE")
MODEL_COMPLEX = os.getenv("MODEL_COMPLEX")
MODEL_DOCUMENT = os.getenv("MODEL_DOCUMENT")
MODEL_CLASSIFIER = os.getenv("MODEL_CLASSIFIER")
MODEL_EVALUATOR = os.getenv("MODEL_EVALUATOR")

# Classification-to-model mapping
CLASSIFICATION_MODEL_MAP = {
    "simple": MODEL_SIMPLE,
    "complex": MODEL_COMPLEX,
    "document": MODEL_DOCUMENT,
}

# Langfuse
LANGFUSE_SECRET_KEY = os.getenv("LANGFUSE_SECRET_KEY", "")
LANGFUSE_PUBLIC_KEY = os.getenv("LANGFUSE_PUBLIC_KEY", "")
LANGFUSE_HOST = os.getenv("LANGFUSE_HOST")

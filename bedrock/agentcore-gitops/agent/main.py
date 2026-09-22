import os

from bedrock_agentcore.runtime import BedrockAgentCoreApp
from pydantic import BaseModel, ConfigDict, Field
from strands import Agent, tool
from strands.models import BedrockModel


app = BedrockAgentCoreApp()


class Invocation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    prompt: str = Field(min_length=1, max_length=8000)


@tool
def deployment_info() -> dict[str, str]:
    """Return this deployment's release and GitOps ownership information."""
    return {
        "release": os.getenv("RELEASE_VERSION", "v1"),
        "build_revision": os.getenv("BUILD_REVISION", "local"),
        "entrypoint": "Amazon Bedrock AgentCore Gateway",
        "platform": "Amazon EKS + Argo CD + ACK",
        "execution": "Amazon Bedrock AgentCore Runtime",
    }


@app.entrypoint
def invoke(payload: dict[str, object]) -> dict[str, str]:
    request = Invocation.model_validate(payload)
    model_id = os.getenv("MODEL_ID", "global.anthropic.claude-sonnet-5")
    model = BedrockModel(
        model_id=model_id,
        region_name=os.getenv("AWS_REGION", "us-east-1"),
        max_tokens=512,
    )
    agent = Agent(
        model=model,
        tools=[deployment_info],
        system_prompt=(
            "You are a concise Korean-speaking DevOps education assistant. "
            "Explain EKS, Argo CD, ACK and AgentCore. You have no infrastructure "
            "mutation permissions. Use deployment_info for the current release. "
            "Do not claim to inspect live clusters or execute commands."
        ),
        callback_handler=None,
    )
    result = agent(request.prompt)
    return {
        "response": str(result),
        "release": os.getenv("RELEASE_VERSION", "v1"),
        "build_revision": os.getenv("BUILD_REVISION", "local"),
        "model_id": model_id,
    }


if __name__ == "__main__":
    app.run()

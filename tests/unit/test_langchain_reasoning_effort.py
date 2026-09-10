from langchain_core.messages import HumanMessage

from industrial_ai_agent.agent.llm import (
    FinishReason,
    LLMReasoningEffort,
    LLMResponse,
    ModelProfile,
)
from industrial_ai_agent.infrastructure.llm.langchain_adapter import LLMClientChatModel


class CapturingLLMClient:
    def __init__(self) -> None:
        self.requests = []

    def chat(self, profile, request):
        self.requests.append((profile, request))
        return LLMResponse(text="ok", finish_reason=FinishReason.STOP)


def test_preserves_reasoning_effort_for_bound_tool_and_response_models() -> None:
    client = CapturingLLMClient()
    model = LLMClientChatModel(
        client,
        ModelProfile("local_quality"),
        reasoning_effort=LLMReasoningEffort.NONE,
        supports_structured_output=True,
    )

    model.bind_tools(()).invoke((HumanMessage(content="hello"),))

    assert client.requests[0][1].reasoning_effort is LLMReasoningEffort.NONE

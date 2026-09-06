from dataclasses import dataclass, field

import pytest

from industrial_ai_agent.agent.langgraph_troubleshooting_agent import (
    _extract_classification,
)
from industrial_ai_agent.agent.llm import (
    FinishReason,
    LLMMessage,
    LLMRequest,
    LLMResponse,
    MessageRole,
    ModelProfile,
)
from industrial_ai_agent.agent.model_egress import (
    EgressCheckedLLMClient,
    ExecutionZone,
    ModelEgressDeniedError,
)
from industrial_ai_agent.domain.security import (
    DEMO_ENGINEER_SECURITY_CONTEXT,
    DataClassification,
    SecurityContext,
)


@dataclass
class _RecordingLLMClient:
    calls: list[LLMRequest] = field(default_factory=list)

    def chat(self, profile: ModelProfile, request: LLMRequest) -> LLMResponse:
        del profile
        self.calls.append(request)
        return LLMResponse(text="ok", finish_reason=FinishReason.STOP)


@dataclass(frozen=True)
class _PublicCloudResolver:
    def get_execution_zone(self, profile_name: str) -> ExecutionZone:
        del profile_name
        return ExecutionZone.PUBLIC_CLOUD

    def get_max_data_classification(self, profile_name: str) -> DataClassification:
        del profile_name
        return DataClassification.PUBLIC


def _request() -> LLMRequest:
    return LLMRequest(
        messages=(LLMMessage(role=MessageRole.USER, content="synthetic request"),)
    )


def test_demo_security_context_is_auth_ready_but_not_authenticated() -> None:
    assert DEMO_ENGINEER_SECURITY_CONTEXT.subject_id == "demo-engineer"
    assert DEMO_ENGINEER_SECURITY_CONTEXT.roles == ("engineer",)
    assert DEMO_ENGINEER_SECURITY_CONTEXT.clearance is DataClassification.CONFIDENTIAL
    assert DEMO_ENGINEER_SECURITY_CONTEXT.authenticated is False


@pytest.mark.parametrize(
    "kwargs",
    [
        {"subject_id": "", "roles": ("engineer",)},
        {"subject_id": "engineer", "roles": ()},
        {"subject_id": "engineer", "roles": ("",)},
    ],
)
def test_security_context_validates_identity_shape(kwargs: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        SecurityContext(
            clearance=DataClassification.CONFIDENTIAL,
            authenticated=False,
            **kwargs,  # type: ignore[arg-type]
        )


def test_observed_confidential_data_monotonically_blocks_public_cloud() -> None:
    adapter = _RecordingLLMClient()
    checked_client = EgressCheckedLLMClient(
        adapter,
        _PublicCloudResolver(),
        DataClassification.PUBLIC,
    )

    checked_client.chat(ModelProfile("public"), _request())
    checked_client.raise_request_classification(DataClassification.CONFIDENTIAL)

    with pytest.raises(ModelEgressDeniedError, match="Model egress denied by policy"):
        checked_client.chat(ModelProfile("public"), _request())

    assert len(adapter.calls) == 1


def test_mcp_json_transport_result_preserves_highest_nested_classification() -> None:
    result = (
        '{"classification": 1, "results": '
        '[{"classification": 2}, {"classification": 3}]}'
    )

    assert _extract_classification(result) is DataClassification.RESTRICTED

from dataclasses import dataclass, field

import pytest

from industrial_ai_agent.agent.llm import (
    FinishReason,
    LLMClient,
    LLMMessage,
    LLMRequest,
    LLMResponse,
    MessageRole,
    ModelProfile,
)
from industrial_ai_agent.agent.model_egress import (
    DataClassification,
    EgressCheckedLLMClient,
    ExecutionZone,
    ModelEgressDeniedError,
    ModelEgressPolicy,
    effective_data_classification,
)

PROFILE = ModelProfile("test-profile")


@dataclass
class RecordingLLMClient:
    calls: list[tuple[ModelProfile, LLMRequest]] = field(default_factory=list)

    def chat(self, profile: ModelProfile, request: LLMRequest) -> LLMResponse:
        self.calls.append((profile, request))
        return LLMResponse(
            text="response",
            finish_reason=FinishReason.STOP,
        )


@dataclass(frozen=True)
class FixedExecutionZoneResolver:
    execution_zone: object | None

    def get_execution_zone(self, profile_name: str) -> object | None:
        del profile_name
        return self.execution_zone


def create_request(content: str = "synthetic request") -> LLMRequest:
    return LLMRequest(messages=(LLMMessage(role=MessageRole.USER, content=content),))


def test_data_classification_has_required_order() -> None:
    assert (
        DataClassification.PUBLIC
        < DataClassification.INTERNAL
        < DataClassification.CONFIDENTIAL
        < DataClassification.RESTRICTED
    )


@pytest.mark.parametrize(
    ("classifications", "expected"),
    [
        (
            (DataClassification.PUBLIC, DataClassification.INTERNAL),
            DataClassification.INTERNAL,
        ),
        (
            (DataClassification.INTERNAL, DataClassification.CONFIDENTIAL),
            DataClassification.CONFIDENTIAL,
        ),
        (
            (
                DataClassification.RESTRICTED,
                DataClassification.PUBLIC,
                DataClassification.INTERNAL,
            ),
            DataClassification.RESTRICTED,
        ),
    ],
)
def test_effective_classification_is_most_restrictive(
    classifications: tuple[DataClassification, ...],
    expected: DataClassification,
) -> None:
    assert effective_data_classification(*classifications) is expected


def test_effective_classification_requires_known_input() -> None:
    with pytest.raises(ValueError, match="At least one data classification"):
        effective_data_classification()

    with pytest.raises(ValueError, match="Unknown data classification"):
        effective_data_classification(DataClassification.PUBLIC, "unknown")  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("classification", "zone", "expected"),
    [
        (DataClassification.PUBLIC, ExecutionZone.LOCAL, True),
        (DataClassification.PUBLIC, ExecutionZone.PUBLIC_CLOUD, True),
        (DataClassification.INTERNAL, ExecutionZone.LOCAL, True),
        (DataClassification.INTERNAL, ExecutionZone.PUBLIC_CLOUD, False),
        (DataClassification.CONFIDENTIAL, ExecutionZone.LOCAL, True),
        (DataClassification.CONFIDENTIAL, ExecutionZone.PUBLIC_CLOUD, False),
        (DataClassification.RESTRICTED, ExecutionZone.LOCAL, True),
        (DataClassification.RESTRICTED, ExecutionZone.PUBLIC_CLOUD, False),
    ],
)
def test_initial_egress_matrix(
    classification: DataClassification,
    zone: ExecutionZone,
    expected: bool,
) -> None:
    assert ModelEgressPolicy().is_allowed(classification, zone) is expected


@pytest.mark.parametrize(
    ("classification", "zone"),
    [
        (None, ExecutionZone.LOCAL),
        ("unknown", ExecutionZone.LOCAL),
        (DataClassification.PUBLIC, None),
        (DataClassification.PUBLIC, "unknown"),
    ],
)
def test_egress_policy_denies_missing_or_unknown_values(
    classification: object | None,
    zone: object | None,
) -> None:
    assert ModelEgressPolicy().is_allowed(classification, zone) is False


@pytest.mark.parametrize(
    ("classification", "zone"),
    [
        (DataClassification.CONFIDENTIAL, ExecutionZone.LOCAL),
        (DataClassification.PUBLIC, ExecutionZone.PUBLIC_CLOUD),
    ],
)
def test_allowed_request_reaches_adapter(
    classification: DataClassification,
    zone: ExecutionZone,
) -> None:
    adapter = RecordingLLMClient()
    client: LLMClient = EgressCheckedLLMClient(
        adapter,
        FixedExecutionZoneResolver(zone),
        classification,
    )
    outbound_request = create_request()

    response = client.chat(PROFILE, outbound_request)

    assert response.text == "response"
    assert adapter.calls == [(PROFILE, outbound_request)]


def test_denied_public_cloud_request_never_reaches_adapter() -> None:
    adapter = RecordingLLMClient()
    client = EgressCheckedLLMClient(
        adapter,
        FixedExecutionZoneResolver(ExecutionZone.PUBLIC_CLOUD),
        DataClassification.CONFIDENTIAL,
    )

    with pytest.raises(ModelEgressDeniedError, match="Model egress denied by policy"):
        client.chat(PROFILE, create_request("confidential production value"))

    assert adapter.calls == []


def test_deny_error_does_not_expose_request_content_or_secrets() -> None:
    adapter = RecordingLLMClient()
    client = EgressCheckedLLMClient(
        adapter,
        FixedExecutionZoneResolver(ExecutionZone.PUBLIC_CLOUD),
        DataClassification.RESTRICTED,
    )

    with pytest.raises(ModelEgressDeniedError) as captured_error:
        client.chat(PROFILE, create_request("secret-request-content"))

    error_message = str(captured_error.value)
    assert error_message == "Model egress denied by policy"
    assert "secret-request-content" not in error_message
    assert adapter.calls == []

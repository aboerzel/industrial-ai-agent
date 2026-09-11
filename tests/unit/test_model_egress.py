from dataclasses import dataclass, field
from pathlib import Path

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
from industrial_ai_agent.infrastructure.llm.configuration import (
    load_llm_configuration,
)

PROFILE = ModelProfile("test-profile")
PROJECT_ROOT = Path(__file__).resolve().parents[2]


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
    max_data_classification: object | None = DataClassification.RESTRICTED

    def get_execution_zone(self, profile_name: str) -> object | None:
        del profile_name
        return self.execution_zone

    def get_max_data_classification(self, profile_name: str) -> object | None:
        del profile_name
        return self.max_data_classification


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
        (DataClassification.INTERNAL, ExecutionZone.PUBLIC_CLOUD, True),
        (DataClassification.CONFIDENTIAL, ExecutionZone.LOCAL, True),
        (DataClassification.CONFIDENTIAL, ExecutionZone.PUBLIC_CLOUD, True),
        (DataClassification.RESTRICTED, ExecutionZone.LOCAL, True),
        (DataClassification.RESTRICTED, ExecutionZone.PUBLIC_CLOUD, False),
    ],
)
def test_initial_egress_matrix(
    classification: DataClassification,
    zone: ExecutionZone,
    expected: bool,
) -> None:
    assert (
        ModelEgressPolicy().is_allowed(
            classification,
            zone,
            (
                DataClassification.RESTRICTED
                if zone is ExecutionZone.LOCAL
                else DataClassification.CONFIDENTIAL
            ),
        )
        is expected
    )


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
    assert (
        ModelEgressPolicy().is_allowed(
            classification, zone, DataClassification.CONFIDENTIAL
        )
        is False
    )


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
        FixedExecutionZoneResolver(
            ExecutionZone.PUBLIC_CLOUD, DataClassification.PUBLIC
        ),
        DataClassification.CONFIDENTIAL,
    )

    with pytest.raises(ModelEgressDeniedError, match="Model egress denied by policy"):
        client.chat(PROFILE, create_request("confidential production value"))

    assert adapter.calls == []


@pytest.mark.parametrize("profile_name", ("mistral_fast", "nvidia_quality"))
def test_s04_confidential_egress_uses_the_same_final_policy_for_new_public_profiles(
    profile_name: str,
) -> None:
    configuration = load_llm_configuration(
        PROJECT_ROOT / "config" / "model_profiles.toml"
    )
    adapter = RecordingLLMClient()
    request = create_request("S04 position-reference observation")
    client = EgressCheckedLLMClient(
        adapter,
        configuration,
        DataClassification.CONFIDENTIAL,
    )

    response = client.chat(ModelProfile(profile_name), request)

    assert response.text == "response"
    assert adapter.calls == [(ModelProfile(profile_name), request)]
    assert ModelEgressPolicy().is_allowed(
        DataClassification.CONFIDENTIAL,
        configuration.get_execution_zone(profile_name),
        configuration.get_max_data_classification(profile_name),
    )


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

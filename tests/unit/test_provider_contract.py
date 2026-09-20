from pathlib import Path

from industrial_ai_agent.agent.llm import (
    FinishReason,
    LLMProviderError,
    LLMProviderErrorCode,
    LLMRequestDiagnostics,
    LLMResponse,
    LLMToolCall,
)
from industrial_ai_agent.infrastructure.llm.configuration import load_model_catalog
from industrial_ai_agent.infrastructure.llm.provider_contract import (
    CapabilityVerification,
    ProviderContractRunner,
    ProviderLiveStatus,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]


class FakeContractClient:
    def __init__(self, responses: list[LLMResponse | Exception]) -> None:
        self._responses = iter(responses)
        self.model_ids: list[str] = []
        self.requests = []

    def chat(self, model_id, request):
        self.model_ids.append(model_id.value)
        self.requests.append(request)
        response = next(self._responses)
        if isinstance(response, Exception):
            raise response
        return response


def _configuration():
    return load_model_catalog(PROJECT_ROOT / "config" / "model_catalog.toml")


def _response(
    *, text: str | None = "OK", tool_calls=(), schema_hash: str | None = None
) -> LLMResponse:
    return LLMResponse(
        text=text,
        tool_calls=tool_calls,
        finish_reason=FinishReason.STOP,
        request_diagnostics=LLMRequestDiagnostics(
            request_payload_bytes=123,
            message_count=1,
            tool_definition_count=0,
            has_tools=False,
            has_structured_output=schema_hash is not None,
            structured_schema_hash=schema_hash,
        ),
    )


def _provider_error(code: LLMProviderErrorCode) -> LLMProviderError:
    return LLMProviderError(
        code,
        provider_error_type="FakeProviderError",
        provider_http_status=429 if code is LLMProviderErrorCode.RATE_LIMIT else 503,
    )


def test_rate_limit_stops_provider_and_does_not_downgrade_capabilities() -> None:
    client = FakeContractClient([_provider_error(LLMProviderErrorCode.RATE_LIMIT)])
    result = ProviderContractRunner(
        _configuration(), environment={"GROQ_API_KEY": "test"}, client=client
    ).run_model("groq_benchmark")

    assert result.live_status is ProviderLiveStatus.RATE_LIMITED
    assert result.text.verification is CapabilityVerification.NOT_VERIFIED
    assert result.structured_output.verification is CapabilityVerification.NOT_VERIFIED
    assert len(client.requests) == 1


def test_timeout_stops_provider_and_does_not_downgrade_capabilities() -> None:
    client = FakeContractClient(
        [_provider_error(LLMProviderErrorCode.PROVIDER_UNAVAILABLE)]
    )
    result = ProviderContractRunner(
        _configuration(), environment={"NVIDIA_API_KEY": "test"}, client=client
    ).run_model("nvidia_quality")

    assert result.live_status is ProviderLiveStatus.UNAVAILABLE
    assert result.text.verification is CapabilityVerification.NOT_VERIFIED
    assert result.tool_calling.verification is CapabilityVerification.NOT_VERIFIED
    assert len(client.requests) == 1


def test_provider_request_rejection_does_not_mark_capability_unsupported() -> None:
    client = FakeContractClient(
        [
            _provider_error(LLMProviderErrorCode.REQUEST_INVALID),
            _provider_error(LLMProviderErrorCode.REQUEST_INVALID),
            _provider_error(LLMProviderErrorCode.REQUEST_INVALID),
            _provider_error(LLMProviderErrorCode.REQUEST_INVALID),
        ]
    )
    result = ProviderContractRunner(
        _configuration(), environment={"GROQ_API_KEY": "test"}, client=client
    ).run_model("groq_benchmark")

    assert result.live_status is ProviderLiveStatus.REQUEST_REJECTED
    assert result.text.verification is CapabilityVerification.NOT_VERIFIED
    assert result.normalized_error == "llm_provider_request_invalid"


def test_missing_external_key_is_not_configured_without_calling_provider() -> None:
    client = FakeContractClient([])
    result = ProviderContractRunner(
        _configuration(), environment={}, client=client
    ).run_model("mistral_fast")

    assert result.live_status is ProviderLiveStatus.NOT_CONFIGURED
    assert result.normalized_error == "model_not_configured"
    assert client.requests == []


def test_groq_same_request_constraint_is_checked_without_live_request() -> None:
    client = FakeContractClient(
        [
            _response(),
            _response(text=None),
        ]
    )
    # The tool response is intentionally invalid, so the run does not reach the
    # same-request check. Invoke the bounded deterministic guard directly instead.
    runner = ProviderContractRunner(
        _configuration(), environment={"GROQ_API_KEY": "test"}, client=client
    )
    result = runner._same_request_constraint("groq_benchmark")

    assert result.verification is CapabilityVerification.UNSUPPORTED
    assert result.normalized_error == "model_capability_mismatch"
    assert client.requests == []


def test_successful_structured_output_and_separate_multistep_are_verified() -> None:
    tool_call = LLMToolCall(
        id="call-contract",
        name="get_test_value",
        arguments={"name": "contract_value"},
    )
    structured = (
        '{"status":"OK","optional_note":null,"retry_count":0,'
        '"severity":"LOW","detail":{"code":"primary","quantity":1},'
        '"items":[{"code":"item","quantity":1}]}'
    )
    client = FakeContractClient(
        [
            _response(),
            _response(text=None, tool_calls=(tool_call,)),
            _response(text=structured, schema_hash="sha256:contract"),
            _response(text=None, tool_calls=(tool_call,)),
            _response(text=structured, schema_hash="sha256:contract"),
        ]
    )
    result = ProviderContractRunner(
        _configuration(), environment={}, client=client
    ).run_model("local_fast")

    assert result.structured_output.verification is CapabilityVerification.VERIFIED
    assert result.structured_output.schema_hash is not None
    assert result.multi_step.verification is CapabilityVerification.VERIFIED
    assert result.live_status is ProviderLiveStatus.AVAILABLE
    assert client.model_ids == ["local_fast"] * 5


def test_safe_json_contains_only_metadata() -> None:
    client = FakeContractClient(
        [
            _response(text="a private response must not be stored"),
            _response(text="a private response must not be stored"),
            _response(text="a private response must not be stored"),
            _response(text="a private response must not be stored"),
        ]
    )
    result = ProviderContractRunner(
        _configuration(), environment={"GROQ_API_KEY": "test"}, client=client
    ).run_model("groq_benchmark")

    serialized = result.safe_json()
    assert "private response" not in serialized
    assert "Reply with the word" not in serialized
    assert "GROQ_API_KEY" not in serialized


def test_runner_uses_only_the_explicit_model_id_without_fallback() -> None:
    client = FakeContractClient([_provider_error(LLMProviderErrorCode.RATE_LIMIT)])
    ProviderContractRunner(
        _configuration(), environment={"GROQ_API_KEY": "test"}, client=client
    ).run_model("groq_benchmark")

    assert client.model_ids == ["groq_benchmark"]

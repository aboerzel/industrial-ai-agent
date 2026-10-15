"""C04 transport-boundary regressions with the real SDK and no external network."""

import httpx
import pytest
from openai import APIStatusError, OpenAI
from test_openai_compatible_llm_client import (
    chat_with_policy,
    create_authenticated_configuration,
    create_configuration,
)

from industrial_ai_agent.agent.llm import LLMMessage, LLMRequest, MessageRole, ModelId
from industrial_ai_agent.agent.model_egress import (
    EgressCheckedLLMClient,
    ExecutionZone,
    ModelEgressDeniedError,
)
from industrial_ai_agent.agent.model_selection import (
    AGENT_CONSUMER,
    CapabilityCheckedLLMClient,
)
from industrial_ai_agent.domain.security import DataClassification
from industrial_ai_agent.infrastructure.llm import openai_compatible as provider_adapter

_SYNTHETIC_KEY = "synthetic-c04-test-key"
_MODEL_ID = ModelId("local_quality")
_REQUEST = LLMRequest(
    messages=(LLMMessage(role=MessageRole.USER, content="SYNTHETIC"),)
)


def _configuration(
    endpoint,
    *,
    source="environment",
    zone=ExecutionZone.PUBLIC_CLOUD,
    authentication="api_key",
):
    template = (
        create_configuration()
        if zone is ExecutionZone.LOCAL
        else create_authenticated_configuration()
    )
    payload = template.model_dump(mode="json", by_alias=True)
    model = payload["models"][0]
    model["authentication"] = authentication
    model["api_key_env"] = "CLOUD_LLM_API_KEY" if authentication == "api_key" else None
    if source == "catalog":
        model["base_url"] = endpoint
    else:
        model["base_url_env"] = "C04_ENDPOINT"
    configuration = type(template).model_validate(payload)
    environment = {"CLOUD_LLM_API_KEY": _SYNTHETIC_KEY}
    if source == "environment":
        environment["C04_ENDPOINT"] = endpoint
    return configuration, environment


class _RecordingProvider:
    def __init__(self, monkeypatch):
        self.guard_calls = []
        self.factories = []
        self.requests = []
        self.credential_lookups = 0
        self.redirect = False
        original_guard = provider_adapter._validate_destination

        def guard(endpoint, zone):
            self.guard_calls.append((endpoint, zone))
            return original_guard(endpoint, zone)

        monkeypatch.setattr(provider_adapter, "_validate_destination", guard)

    def transport(self, request):
        # Retain presence only, never the synthetic credential value.
        self.requests.append(
            (str(request.url), bool(request.headers.get("authorization")))
        )
        if self.redirect:
            return httpx.Response(
                307,
                headers={"location": "http://downgrade.invalid/v1/chat/completions"},
            )
        return httpx.Response(
            200,
            json={
                "id": "synthetic",
                "object": "chat.completion",
                "created": 0,
                "model": "synthetic",
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": "SYNTHETIC"},
                        "finish_reason": "stop",
                    }
                ],
            },
        )

    def factory(self, **kwargs):
        self.factories.append(kwargs["base_url"])
        client = kwargs["http_client"]
        assert client.trust_env is False
        assert client.follow_redirects is False
        client.close()
        kwargs["http_client"] = httpx.Client(
            transport=httpx.MockTransport(self.transport),
            trust_env=False,
            follow_redirects=False,
        )
        return OpenAI(**kwargs)

    def adapter(self, monkeypatch, configuration, environment):
        adapter = provider_adapter.OpenAICompatibleLLMClient(
            configuration, environment=environment, client_factory=self.factory
        )
        original_resolver = adapter._resolve_api_key

        def resolve(profile):
            self.credential_lookups += 1
            return original_resolver(profile)

        monkeypatch.setattr(adapter, "_resolve_api_key", resolve)
        return adapter

    def assert_denied(self, endpoint, zone=ExecutionZone.PUBLIC_CLOUD):
        assert self.guard_calls == [(endpoint, zone)]
        assert self.credential_lookups == 0
        assert self.factories == []
        assert self.requests == []


def _authorized_client(
    adapter, configuration, classification=DataClassification.PUBLIC
):
    return CapabilityCheckedLLMClient(
        EgressCheckedLLMClient(adapter, configuration, classification),
        configuration,
        consumer_id=AGENT_CONSUMER,
        data_classification=classification,
    )


@pytest.mark.parametrize("source", ["catalog", "environment"])
@pytest.mark.parametrize("invocation", ["direct", "authorized"])
@pytest.mark.parametrize("authentication", ["api_key", "none"])
def test_public_http_denied_before_credentials_sdk_and_transport(
    source, invocation, authentication, monkeypatch, caplog, capsys
):
    endpoint = "http://synthetic-provider.invalid/v1"
    configuration, environment = _configuration(
        endpoint, source=source, authentication=authentication
    )
    recording = _RecordingProvider(monkeypatch)
    with recording.adapter(monkeypatch, configuration, environment) as adapter:
        client = (
            adapter
            if invocation == "direct"
            else _authorized_client(adapter, configuration)
        )
        if invocation == "direct":
            from industrial_ai_agent.agent.model_egress import ModelExecutionAuthorizer

            outbound = ModelExecutionAuthorizer().authorize_request(
                _MODEL_ID,
                _REQUEST,
                DataClassification.PUBLIC,
                configuration.get_execution_zone(_MODEL_ID.value),
                configuration.get_max_data_classification(_MODEL_ID.value),
            )
        else:
            outbound = _REQUEST
        with pytest.raises(PermissionError) as denied:
            client.chat(_MODEL_ID, outbound)
        assert type(denied.value) is PermissionError
        recording.assert_denied(endpoint)
        captured = capsys.readouterr()
        assert (
            _SYNTHETIC_KEY
            not in str(denied.value) + caplog.text + captured.out + captured.err
        )


def test_public_http_denied_even_when_configured_credential_is_missing(monkeypatch):
    endpoint = "http://synthetic-provider.invalid/v1"
    configuration, environment = _configuration(endpoint)
    environment.pop("CLOUD_LLM_API_KEY")
    recording = _RecordingProvider(monkeypatch)
    with recording.adapter(monkeypatch, configuration, environment) as adapter:
        with pytest.raises(PermissionError):
            chat_with_policy(adapter, _MODEL_ID, _REQUEST)
        recording.assert_denied(endpoint)


@pytest.mark.parametrize("source", ["catalog", "environment"])
@pytest.mark.parametrize(
    "endpoint",
    [
        "https://synthetic-provider.invalid/v1",
        "HTTPS://synthetic-provider.invalid:8443/prefix/v1",
    ],
)
def test_public_https_preserves_sdk_response_and_attaches_credential_only_to_tls(
    source, endpoint, monkeypatch
):
    configuration, environment = _configuration(endpoint, source=source)
    effective = (
        endpoint if source == "environment" else str(configuration.models[0].base_url)
    )
    recording = _RecordingProvider(monkeypatch)
    with recording.adapter(monkeypatch, configuration, environment) as adapter:
        response = _authorized_client(adapter, configuration).chat(_MODEL_ID, _REQUEST)
        assert response.text == "SYNTHETIC"
        assert response.finish_reason.value == "stop"
        assert recording.guard_calls == [(effective, ExecutionZone.PUBLIC_CLOUD)]
        assert len(recording.factories) == recording.credential_lookups == 1
        assert len(recording.requests) == 1
        assert httpx.URL(recording.requests[0][0]).scheme == "https"
        assert recording.requests[0][1] is True


@pytest.mark.parametrize("source", ["catalog", "environment"])
@pytest.mark.parametrize(
    "host", ["localhost", "127.0.0.1", "[::1]", "host.docker.internal"]
)
def test_approved_local_http_remains_allowed(source, host, monkeypatch):
    endpoint = f"http://{host}:11434/v1"
    configuration, environment = _configuration(
        endpoint, source=source, zone=ExecutionZone.LOCAL, authentication="none"
    )
    recording = _RecordingProvider(monkeypatch)
    with recording.adapter(monkeypatch, configuration, environment) as adapter:
        response = _authorized_client(
            adapter, configuration, DataClassification.RESTRICTED
        ).chat(_MODEL_ID, _REQUEST)
        assert response.text == "SYNTHETIC"
        assert recording.guard_calls == [(endpoint, ExecutionZone.LOCAL)]
        assert len(recording.factories) == len(recording.requests) == 1
        assert httpx.URL(recording.requests[0][0]).scheme == "http"


@pytest.mark.parametrize(
    "endpoint",
    [
        "ftp://synthetic-provider.invalid/v1",
        "file://synthetic-provider.invalid/v1",
        "ws://synthetic-provider.invalid/v1",
        "custom://synthetic-provider.invalid/v1",
        "https://synthetic-user:synthetic-pass@synthetic-provider.invalid/v1",
        "https://synthetic-provider.invalid/v1#fragment",
        "https://synthetic-provider.invalid/v1?query=synthetic",
    ],
)
def test_unsafe_endpoint_override_reaches_guard_and_denies_before_transport(
    endpoint, monkeypatch
):
    configuration, environment = _configuration(endpoint)
    recording = _RecordingProvider(monkeypatch)
    with recording.adapter(monkeypatch, configuration, environment) as adapter:
        with pytest.raises(ValueError) as denied:
            chat_with_policy(adapter, _MODEL_ID, _REQUEST)
        assert type(denied.value) is ValueError
        recording.assert_denied(endpoint)
        assert "synthetic-pass" not in str(denied.value)
        assert _SYNTHETIC_KEY not in str(denied.value)


def test_public_https_redirect_to_http_is_not_followed(monkeypatch):
    endpoint = "https://synthetic-provider.invalid/v1"
    configuration, environment = _configuration(endpoint)
    recording = _RecordingProvider(monkeypatch)
    recording.redirect = True
    with recording.adapter(monkeypatch, configuration, environment) as adapter:
        with pytest.raises(APIStatusError) as redirected:
            chat_with_policy(adapter, _MODEL_ID, _REQUEST)
        assert redirected.value.status_code == 307
        assert recording.guard_calls == [(endpoint, ExecutionZone.PUBLIC_CLOUD)]
        assert recording.requests == [(endpoint + "/chat/completions", True)]


def test_environment_proxy_settings_do_not_override_transport_policy(monkeypatch):
    for name in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY"):
        monkeypatch.setenv(
            name, "http://synthetic-proxy.invalid:8080" if name != "NO_PROXY" else ""
        )
    endpoint = "https://synthetic-provider.invalid/v1"
    configuration, environment = _configuration(endpoint)
    recording = _RecordingProvider(monkeypatch)
    with recording.adapter(monkeypatch, configuration, environment) as adapter:
        assert chat_with_policy(adapter, _MODEL_ID, _REQUEST).text == "SYNTHETIC"
        assert recording.requests == [(endpoint + "/chat/completions", True)]


def test_restricted_public_cloud_denial_remains_independent_of_https(monkeypatch):
    endpoint = "https://synthetic-provider.invalid/v1"
    configuration, environment = _configuration(endpoint)
    recording = _RecordingProvider(monkeypatch)
    with recording.adapter(monkeypatch, configuration, environment) as adapter:
        with pytest.raises(ModelEgressDeniedError):
            _authorized_client(
                adapter, configuration, DataClassification.RESTRICTED
            ).chat(_MODEL_ID, _REQUEST)
        assert recording.guard_calls == []
        assert recording.factories == recording.requests == []
        assert recording.credential_lookups == 0

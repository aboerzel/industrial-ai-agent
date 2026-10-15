"""Exact raw-provider bypass, issued-context binding and real SDK MockTransport controls."""

import json
from dataclasses import FrozenInstanceError

import httpx
import pytest
from openai import OpenAI

from industrial_ai_agent.agent.llm import (
    LLMMessage,
    LLMRequest,
    LLMToolDefinition,
    MessageRole,
    ModelEgressAuthorization,
    ModelId,
)
from industrial_ai_agent.agent.model_egress import (
    EgressCheckedLLMClient,
    ModelEgressDeniedError,
    ModelExecutionAuthorizer,
)
from industrial_ai_agent.domain.security import DataClassification
from industrial_ai_agent.infrastructure.llm import openai_compatible as provider
from industrial_ai_agent.infrastructure.llm.configuration import (
    ModelCatalogConfiguration,
)

MODEL = ModelId("synthetic_model")
PROMPT = "SYNTHETIC PROTECTED R01 INPUT"


def configuration(
    endpoint="https://provider.invalid/v1", zone="PUBLIC_CLOUD", ceiling="PUBLIC"
):
    return ModelCatalogConfiguration.model_validate(
        {
            "models": [
                {
                    "id": MODEL.value,
                    "display_name": "Synthetic",
                    "provider": "synthetic",
                    "provider_model": "synthetic",
                    "base_url": endpoint,
                    "temperature": 0,
                    "authentication": "api_key",
                    "api_key_env": "SYNTHETIC_R01_KEY",
                    "execution_zone": zone,
                    "max_data_classification": ceiling,
                    "capabilities": ["text", "tool_calling"],
                    "quality_class": "HIGH",
                    "cost_class": "LOW",
                }
            ]
        }
    )


def request():
    return LLMRequest(messages=(LLMMessage(role=MessageRole.USER, content=PROMPT),))


def authorize(req, config, classification=DataClassification.PUBLIC):
    return ModelExecutionAuthorizer().authorize_request(
        MODEL,
        req,
        classification,
        config.get_execution_zone(MODEL.value),
        config.get_max_data_classification(MODEL.value),
    )


class Probe:
    def __init__(self, monkeypatch, config):
        self.credentials = self.sdk = self.serializations = 0
        self.transport = []
        self.adapter = provider.OpenAICompatibleLLMClient(
            config,
            environment={"SYNTHETIC_R01_KEY": "synthetic-not-a-real-key"},
            client_factory=self.factory,
            http_client_factory=lambda: httpx.Client(
                transport=httpx.MockTransport(self.send),
                trust_env=False,
                follow_redirects=False,
            ),
        )
        resolve = self.adapter._resolve_api_key
        serialize = provider._serialize_message

        def credential(model):
            self.credentials += 1
            return resolve(model)

        def serialization(message):
            self.serializations += 1
            return serialize(message)

        monkeypatch.setattr(self.adapter, "_resolve_api_key", credential)
        monkeypatch.setattr(provider, "_serialize_message", serialization)

    def factory(self, **kwargs):
        self.sdk += 1
        return OpenAI(**kwargs)

    def send(self, req):
        self.transport.append(req)
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

    def untouched(self):
        assert (
            self.credentials,
            self.sdk,
            self.serializations,
            len(self.transport),
        ) == (0, 0, 0, 0)


def test_raw_valid_https_adapter_denies_missing_authorization_before_every_provider_boundary(
    monkeypatch, caplog, capsys
):
    probe = Probe(monkeypatch, configuration())
    with probe.adapter:
        with pytest.raises(
            ModelEgressDeniedError, match="Model egress denied by policy"
        ) as error:
            probe.adapter.chat(MODEL, request())
        probe.untouched()
    output = capsys.readouterr()
    assert PROMPT not in str(error.value) + caplog.text + output.out + output.err
    assert (
        "synthetic-not-a-real-key"
        not in str(error.value) + caplog.text + output.out + output.err
    )


@pytest.mark.parametrize(
    "forgery",
    [
        True,
        {"authorized": True, "classification": "PUBLIC"},
        "PUBLIC",
        object.__new__(ModelEgressAuthorization),
    ],
)
def test_raw_adapter_does_not_trust_forged_decision_or_caller_label(
    monkeypatch, forgery
):
    probe = Probe(monkeypatch, configuration())
    req = request()
    req._egress_authorization = forgery
    with probe.adapter:
        with pytest.raises(ModelEgressDeniedError):
            probe.adapter.chat(MODEL, req)
        probe.untouched()


def test_caller_label_on_otherwise_valid_request_cannot_authorize_egress(monkeypatch):
    probe = Probe(monkeypatch, configuration())
    req = request().model_copy(
        update={"classification": DataClassification.PUBLIC, "authorized": True}
    )
    with probe.adapter:
        with pytest.raises(ModelEgressDeniedError):
            probe.adapter.chat(MODEL, req)
        probe.untouched()


@pytest.mark.parametrize("invocation", ["direct-issued", "wrapped"])
def test_public_cloud_https_positive_control_reaches_real_mock_transport_once(
    monkeypatch, invocation
):
    config = configuration()
    probe = Probe(monkeypatch, config)
    original = request()
    with probe.adapter:
        result = (
            probe.adapter.chat(MODEL, authorize(original, config))
            if invocation == "direct-issued"
            else EgressCheckedLLMClient(
                probe.adapter, config, DataClassification.PUBLIC
            ).chat(MODEL, original)
        )
        assert result.text == "SYNTHETIC"
        assert (
            probe.credentials,
            probe.sdk,
            probe.serializations,
            len(probe.transport),
        ) == (1, 1, 1, 1)
        body = json.loads(probe.transport[0].content)
        assert body["messages"][0]["content"] == PROMPT
        assert "egress_authorization" not in body
        assert original.egress_authorization is None


@pytest.mark.parametrize("classification", [None, DataClassification.RESTRICTED])
def test_missing_or_restricted_classification_is_refused_by_one_policy(
    monkeypatch, classification
):
    config = configuration()
    probe = Probe(monkeypatch, config)
    with probe.adapter:
        with pytest.raises(ModelEgressDeniedError):
            EgressCheckedLLMClient(probe.adapter, config, classification).chat(
                MODEL, request()
            )
        with pytest.raises(ModelEgressDeniedError):
            authorize(request(), config, classification)
        probe.untouched()


@pytest.mark.parametrize("ceiling,allowed", [("PUBLIC", False), ("CONFIDENTIAL", True)])
def test_confidential_cloud_behavior_preserves_current_matrix(
    monkeypatch, ceiling, allowed
):
    config = configuration(ceiling=ceiling)
    probe = Probe(monkeypatch, config)
    with probe.adapter:
        client = EgressCheckedLLMClient(
            probe.adapter, config, DataClassification.CONFIDENTIAL
        )
        if allowed:
            assert client.chat(MODEL, request()).text == "SYNTHETIC"
            assert len(probe.transport) == 1
        else:
            with pytest.raises(ModelEgressDeniedError):
                client.chat(MODEL, request())
            probe.untouched()


@pytest.mark.parametrize(
    "mismatch",
    [
        "model",
        "zone",
        "ceiling",
        "request-copy",
        "request-replacement",
        "stolen-decision",
    ],
)
def test_authorization_cannot_be_reused_in_another_context(monkeypatch, mismatch):
    config = configuration()
    probe = Probe(monkeypatch, config)
    policy_config = config
    model = MODEL
    if mismatch == "model":
        model = ModelId("other_model")
        probe.adapter._configuration = config.model_copy(
            update={
                "models": (
                    *config.models,
                    config.models[0].model_copy(update={"id": model.value}),
                )
            }
        )
    elif mismatch == "zone":
        policy_config = configuration("http://localhost:11434/v1", "LOCAL")
    elif mismatch == "ceiling":
        policy_config = configuration(ceiling="CONFIDENTIAL")
    req = authorize(request(), policy_config)
    if mismatch == "request-copy":
        req = req.model_copy()
    elif mismatch == "request-replacement":
        req = req.model_copy(
            update={
                "messages": (
                    LLMMessage(
                        role=MessageRole.USER, content="Different synthetic input"
                    ),
                )
            }
        )
    elif mismatch == "stolen-decision":
        other = request()
        other._egress_authorization = req.egress_authorization
        req = other
    with probe.adapter:
        with pytest.raises(ModelEgressDeniedError):
            probe.adapter.chat(model, req)
        probe.untouched()


@pytest.mark.parametrize(
    "host", ["localhost", "127.0.0.1", "[::1]", "host.docker.internal"]
)
def test_approved_local_execution_still_requires_and_accepts_policy_decision(
    monkeypatch, host
):
    config = configuration(f"http://{host}:11434/v1", "LOCAL", "RESTRICTED")
    probe = Probe(monkeypatch, config)
    with probe.adapter:
        with pytest.raises(ModelEgressDeniedError):
            probe.adapter.chat(MODEL, request())
        probe.untouched()
        assert (
            EgressCheckedLLMClient(probe.adapter, config, DataClassification.RESTRICTED)
            .chat(MODEL, request())
            .text
            == "SYNTHETIC"
        )
        assert len(probe.transport) == 1


def test_valid_authorization_does_not_bypass_c04_https_requirement(monkeypatch):
    config = configuration("http://provider.invalid/v1")
    probe = Probe(monkeypatch, config)
    with probe.adapter:
        with pytest.raises(PermissionError, match="must use HTTPS"):
            probe.adapter.chat(MODEL, authorize(request(), config))
        probe.untouched()


def test_authorization_is_not_public_request_input_and_cannot_be_constructed_normally():
    original = request()
    authorized = authorize(original, configuration())
    assert authorized is not original
    assert authorized.model_dump() == original.model_dump()
    assert authorized.model_dump_json() == original.model_dump_json()
    assert "egress_authorization" not in LLMRequest.model_json_schema()["properties"]
    assert "ModelEgressAuthorization" not in repr(authorized)
    with pytest.raises(TypeError):
        ModelEgressAuthorization()
    with pytest.raises(FrozenInstanceError):
        authorized.egress_authorization.execution_zone = "LOCAL"


def test_original_nested_inputs_cannot_change_the_policy_authorized_copy(monkeypatch):
    config = configuration()
    probe = Probe(monkeypatch, config)
    original = LLMRequest(
        messages=request().messages,
        tools=(
            LLMToolDefinition(
                name="synthetic_read",
                description="Synthetic",
                parameters={
                    "type": "object",
                    "description": "Approved synthetic schema",
                },
            ),
        ),
    )
    authorized = authorize(original, config)
    original.tools[0].parameters["description"] = "Unapproved later mutation"
    with probe.adapter:
        probe.adapter.chat(MODEL, authorized)
    payload = json.loads(probe.transport[0].content)
    assert (
        payload["tools"][0]["function"]["parameters"]["description"]
        == "Approved synthetic schema"
    )


def test_policy_raise_does_not_leave_the_original_request_authorized_for_raw_reuse(
    monkeypatch,
):
    config = configuration()
    probe = Probe(monkeypatch, config)
    original = request()
    wrapped = EgressCheckedLLMClient(probe.adapter, config, DataClassification.PUBLIC)
    with probe.adapter:
        wrapped.chat(MODEL, original)
        wrapped.raise_request_classification(DataClassification.RESTRICTED)
        with pytest.raises(ModelEgressDeniedError):
            wrapped.chat(MODEL, original)
        with pytest.raises(ModelEgressDeniedError):
            probe.adapter.chat(MODEL, original)
    assert len(probe.transport) == 1


def test_raw_denial_control_reaches_the_authorization_guard_not_schema_validation(
    monkeypatch,
):
    probe = Probe(monkeypatch, configuration())
    with probe.adapter:
        with pytest.raises(ModelEgressDeniedError):
            probe.adapter.chat(MODEL, request())
        probe.untouched()
        # Deliberately remove this one guard in the synthetic fixture: the valid
        # endpoint/request/SDK must then reach MockTransport, proving guard relevance.
        monkeypatch.setattr(
            provider, "require_model_egress_authorization", lambda *args: None
        )
        assert probe.adapter.chat(MODEL, request()).text == "SYNTHETIC"
        assert len(probe.transport) == 1


def test_production_agent_composition_issues_authorization_for_real_mock_adapter(
    monkeypatch,
):
    from langchain_core.messages import HumanMessage

    from industrial_ai_agent.agent.run_classification_policy import (
        AgentRunClassificationPolicy,
        AgentRunProfile,
    )
    from industrial_ai_agent.infrastructure import (
        troubleshooting_run_composition as composition,
    )

    config = configuration()
    probe = Probe(monkeypatch, config)
    monkeypatch.setattr(
        composition, "OpenAICompatibleLLMClient", lambda _: probe.adapter
    )
    # Retain the actual composition, capability wrapper, egress policy and SDK.
    # Only graph/MCP execution is unnecessary for this boundary test.
    monkeypatch.setattr(
        composition, "LangGraphTroubleshootingAgent", lambda model, **kwargs: model
    )
    factory = composition._LangGraphTroubleshootingAgentFactory(
        configuration=config,
        mcp_tool_provider_factory=lambda _: object(),
        authorizer=ModelExecutionAuthorizer(),
    )
    policy = AgentRunClassificationPolicy().resolve(AgentRunProfile.PUBLIC_INFORMATION)
    with factory.open_agent(model_id=MODEL, run_policy=policy) as model:
        assert model.invoke([HumanMessage(content=PROMPT)]).content == "SYNTHETIC"
    assert len(probe.transport) == 1


def test_production_rca_composition_issues_authorization_for_real_mock_adapter(
    monkeypatch,
):
    from industrial_ai_agent.agent.llm import LLMJsonSchema, LLMResponseFormat
    from industrial_ai_agent.application.rca_reasoning import RcaFocus
    from industrial_ai_agent.infrastructure.rca_mcp_server import _reasoning_llm_client

    config = configuration()
    config = config.model_copy(
        update={
            "models": (
                config.models[0].model_copy(
                    update={
                        "capabilities": config.models[0].capabilities
                        | {"structured_output"}
                    }
                ),
            )
        }
    )
    probe = Probe(monkeypatch, config)
    req = LLMRequest(
        messages=request().messages,
        response_format=LLMResponseFormat(
            json_schema=LLMJsonSchema(
                name="synthetic_rca",
                schema_definition={"type": "object", "additionalProperties": False},
            )
        ),
    )
    with probe.adapter:
        client = _reasoning_llm_client(
            probe.adapter,
            configuration=config,
            classification=DataClassification.PUBLIC,
            focus=RcaFocus.OVERVIEW,
            telemetry=None,
        )
        assert client.chat(MODEL, req).text == "SYNTHETIC"
    assert len(probe.transport) == 1

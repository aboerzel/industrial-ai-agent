from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from openai import APIStatusError, BadRequestError, RateLimitError

from industrial_ai_agent.agent.llm import (
    FinishReason,
    LLMJsonSchema,
    LLMMessage,
    LLMProviderError,
    LLMProviderErrorCode,
    LLMReasoningEffort,
    LLMRequest,
    LLMResponseFormat,
    LLMToolCall,
    LLMToolDefinition,
    MessageRole,
    ModelProfile,
)
from industrial_ai_agent.infrastructure.llm.configuration import (
    LLMConfiguration,
    load_llm_configuration,
)
from industrial_ai_agent.infrastructure.llm.openai_compatible import (
    OpenAICompatibleLLMClient,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
LOCAL_QUALITY_PROFILE = ModelProfile("local_quality")
GROQ_BENCHMARK_PROFILE = ModelProfile("groq_benchmark")
MISTRAL_FAST_PROFILE = ModelProfile("mistral_fast")
NVIDIA_QUALITY_PROFILE = ModelProfile("nvidia_quality")


class FakeCompletions:
    def __init__(self, completion: SimpleNamespace | Exception) -> None:
        self.completion = completion
        self.parameters: dict[str, Any] | None = None

    def create(self, **parameters: Any) -> SimpleNamespace:
        self.parameters = parameters
        if isinstance(self.completion, Exception):
            raise self.completion
        return self.completion


class FakeOpenAIClient:
    def __init__(self, completion: SimpleNamespace | Exception) -> None:
        self.completions = FakeCompletions(completion)
        self.chat = SimpleNamespace(completions=self.completions)
        self.closed = False

    def close(self) -> None:
        self.closed = True


def create_configuration(
    *,
    supports_structured_output: bool = False,
    supports_reasoning_effort: bool = False,
    provider: str = "ollama",
    max_output_tokens: int | None = None,
) -> LLMConfiguration:
    return LLMConfiguration.model_validate(
        {
            "models": [
                {
                    "id": "local_quality",
                    "display_name": "Local Quality",
                    "provider": provider,
                    "provider_model": "qwen3.5:9b",
                    "base_url": "http://localhost:11434/v1",
                    "temperature": 0,
                    "authentication": "none",
                    "execution_zone": "LOCAL",
                    "max_data_classification": "RESTRICTED",
                    "capabilities": [
                        "text",
                        "tool_calling",
                        *(["structured_output"] if supports_structured_output else []),
                    ],
                    "quality_class": "HIGH",
                    "cost_class": "LOW",
                    "supports_reasoning_effort": supports_reasoning_effort,
                    "max_output_tokens": max_output_tokens,
                }
            ]
        }
    )


def test_passes_supported_structured_output_request_to_provider() -> None:
    completion = SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(content='{"summary":"ok"}', tool_calls=None),
                finish_reason="stop",
            )
        ]
    )
    fake_client = FakeOpenAIClient(completion)
    client = OpenAICompatibleLLMClient(
        create_configuration(
            supports_structured_output=True,
            supports_reasoning_effort=True,
        ),
        environment={},
        client_factory=lambda **_: fake_client,
    )
    request = LLMRequest(
        messages=(LLMMessage(role=MessageRole.USER, content="Hello"),),
        response_format=LLMResponseFormat(
            json_schema=LLMJsonSchema(
                name="test_response",
                schema_definition={"type": "object", "additionalProperties": False},
            )
        ),
        reasoning_effort=LLMReasoningEffort.NONE,
    )

    client.chat(LOCAL_QUALITY_PROFILE, request)

    assert fake_client.completions.parameters is not None
    assert fake_client.completions.parameters["response_format"] == {
        "type": "json_schema",
        "json_schema": {
            "name": "test_response",
            "schema": {"type": "object", "additionalProperties": False},
            "strict": True,
        },
    }
    assert fake_client.completions.parameters["reasoning_effort"] == "none"
    assert "extra_body" not in fake_client.completions.parameters


def test_passes_reasoning_effort_to_non_ollama_provider() -> None:
    completion = SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(content="ok", tool_calls=None),
                finish_reason="stop",
            )
        ]
    )
    fake_client = FakeOpenAIClient(completion)
    client = OpenAICompatibleLLMClient(
        create_configuration(supports_reasoning_effort=True, provider="groq"),
        environment={},
        client_factory=lambda **_: fake_client,
    )

    client.chat(
        LOCAL_QUALITY_PROFILE,
        LLMRequest(
            messages=(LLMMessage(role=MessageRole.USER, content="Hello"),),
            reasoning_effort=LLMReasoningEffort.NONE,
        ),
    )

    assert fake_client.completions.parameters is not None
    assert fake_client.completions.parameters["reasoning_effort"] == "none"


def test_passes_configured_output_limit_to_provider() -> None:
    completion = SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(content="ok", tool_calls=None),
                finish_reason="stop",
            )
        ]
    )
    fake_client = FakeOpenAIClient(completion)
    client = OpenAICompatibleLLMClient(
        create_configuration(max_output_tokens=128),
        environment={},
        client_factory=lambda **_: fake_client,
    )

    client.chat(
        LOCAL_QUALITY_PROFILE,
        LLMRequest(messages=(LLMMessage(role=MessageRole.USER, content="Hello"),)),
    )

    assert fake_client.completions.parameters is not None
    assert fake_client.completions.parameters["max_tokens"] == 128


def test_normalizes_provider_parsed_structured_response_object() -> None:
    completion = SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(
                    content=None,
                    parsed={"answer": "S04 reports QUALITY-09.", "next_steps": []},
                    tool_calls=None,
                ),
                finish_reason="stop",
            )
        ]
    )
    client = OpenAICompatibleLLMClient(
        create_configuration(supports_structured_output=True),
        environment={},
        client_factory=lambda **_: FakeOpenAIClient(completion),
    )

    response = client.chat(
        LOCAL_QUALITY_PROFILE,
        LLMRequest(
            messages=(LLMMessage(role=MessageRole.USER, content="Hello"),),
            response_format=LLMResponseFormat(
                json_schema=LLMJsonSchema(name="test_response", schema_definition={})
            ),
        ),
    )

    assert response.text == '{"answer":"S04 reports QUALITY-09.","next_steps":[]}'


def test_normalizes_provider_text_content_blocks() -> None:
    completion = SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(
                    content=[
                        {"type": "text", "text": '{"answer":"S04 '},
                        {"type": "text", "text": 'reports QUALITY-09."}'},
                    ],
                    tool_calls=None,
                ),
                finish_reason="stop",
            )
        ]
    )
    client = OpenAICompatibleLLMClient(
        create_configuration(supports_structured_output=True),
        environment={},
        client_factory=lambda **_: FakeOpenAIClient(completion),
    )

    response = client.chat(
        LOCAL_QUALITY_PROFILE,
        LLMRequest(
            messages=(LLMMessage(role=MessageRole.USER, content="Hello"),),
            response_format=LLMResponseFormat(
                json_schema=LLMJsonSchema(name="test_response", schema_definition={})
            ),
        ),
    )

    assert response.text == '{"answer":"S04 reports QUALITY-09."}'


def test_rejects_structured_output_for_unsupported_profile() -> None:
    completion = SimpleNamespace(choices=[])
    client = OpenAICompatibleLLMClient(
        create_configuration(),
        environment={},
        client_factory=lambda **_: FakeOpenAIClient(completion),
    )
    request = LLMRequest(
        messages=(LLMMessage(role=MessageRole.USER, content="Hello"),),
        response_format=LLMResponseFormat(
            json_schema=LLMJsonSchema(
                name="test_response", schema_definition={"type": "object"}
            )
        ),
    )

    with pytest.raises(ValueError, match="does not support structured response"):
        client.chat(LOCAL_QUALITY_PROFILE, request)


def test_rejects_reasoning_effort_for_unsupported_profile() -> None:
    completion = SimpleNamespace(choices=[])
    client = OpenAICompatibleLLMClient(
        create_configuration(supports_structured_output=True),
        environment={},
        client_factory=lambda **_: FakeOpenAIClient(completion),
    )
    request = LLMRequest(
        messages=(LLMMessage(role=MessageRole.USER, content="Hello"),),
        reasoning_effort=LLMReasoningEffort.NONE,
    )

    with pytest.raises(ValueError, match="does not support reasoning-effort"):
        client.chat(LOCAL_QUALITY_PROFILE, request)


def create_authenticated_configuration() -> LLMConfiguration:
    return LLMConfiguration.model_validate(
        {
            "models": [
                {
                    "id": "local_quality",
                    "display_name": "Cloud Model",
                    "provider": "cloud-provider",
                    "provider_model": "cloud-model",
                    "base_url": "https://llm.example.com/v1",
                    "temperature": 0,
                    "authentication": "api_key",
                    "api_key_env": "CLOUD_LLM_API_KEY",
                    "execution_zone": "PUBLIC_CLOUD",
                    "max_data_classification": "CONFIDENTIAL",
                    "capabilities": ["text"],
                    "quality_class": "HIGH",
                    "cost_class": "LOW",
                }
            ]
        }
    )


def test_maps_chat_request_and_text_response_without_network_call() -> None:
    completion = SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(
                    content="Likely sensor contamination.", tool_calls=None
                ),
                finish_reason="stop",
            )
        ]
    )
    fake_client = FakeOpenAIClient(completion)
    factory_arguments: dict[str, str] = {}

    def client_factory(**arguments: str) -> FakeOpenAIClient:
        factory_arguments.update(arguments)
        return fake_client

    client = OpenAICompatibleLLMClient(
        create_configuration(),
        environment={},
        client_factory=client_factory,
    )
    request = LLMRequest(
        messages=(LLMMessage(role=MessageRole.USER, content="Why was P4711 rejected?"),)
    )

    response = client.chat(LOCAL_QUALITY_PROFILE, request)

    assert factory_arguments == {
        "api_key": "not-used",
        "base_url": "http://localhost:11434/v1",
        "max_retries": 0,
        "timeout": 45.0,
    }
    assert fake_client.completions.parameters == {
        "model": "qwen3.5:9b",
        "messages": [{"role": "user", "content": "Why was P4711 rejected?"}],
        "temperature": 0.0,
    }
    assert response.text == "Likely sensor contamination."
    assert response.finish_reason is FinishReason.STOP
    assert response.tool_calls == ()


def test_maps_tool_definitions_and_tool_calls_without_executing_them() -> None:
    completion = SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(
                    content=None,
                    tool_calls=[
                        SimpleNamespace(
                            id="call-1",
                            function=SimpleNamespace(
                                name="get_product_history",
                                arguments='{"product_id":"P4711"}',
                            ),
                        )
                    ],
                ),
                finish_reason="tool_calls",
            )
        ]
    )
    fake_client = FakeOpenAIClient(completion)
    client = OpenAICompatibleLLMClient(
        create_configuration(),
        environment={},
        client_factory=lambda **_: fake_client,
    )
    request = LLMRequest(
        messages=(LLMMessage(role=MessageRole.USER, content="Inspect P4711"),),
        tools=(
            LLMToolDefinition(
                name="get_product_history",
                description="Get the production history for a product.",
                parameters={
                    "type": "object",
                    "properties": {"product_id": {"type": "string"}},
                    "required": ["product_id"],
                },
            ),
        ),
    )

    response = client.chat(LOCAL_QUALITY_PROFILE, request)

    assert response.text is None
    assert response.finish_reason is FinishReason.TOOL_CALLS
    assert response.tool_calls[0].name == "get_product_history"
    assert response.tool_calls[0].arguments == {"product_id": "P4711"}
    assert fake_client.completions.parameters is not None
    assert fake_client.completions.parameters["tools"][0]["function"]["name"] == (
        "get_product_history"
    )
    assert fake_client.completions.parameters["parallel_tool_calls"] is False


@pytest.mark.parametrize(
    ("profile", "api_key_env", "api_key", "model_override", "base_url_override"),
    (
        (
            MISTRAL_FAST_PROFILE,
            "MISTRAL_API_KEY",
            "mistral-test-key",
            "mistral-override",
            "https://mistral.example.test/v1",
        ),
        (
            NVIDIA_QUALITY_PROFILE,
            "NVIDIA_API_KEY",
            "nvidia-test-key",
            "nvidia-override",
            "https://nvidia.example.test/v1",
        ),
    ),
)
def test_external_profiles_reuse_openai_compatible_tool_and_usage_contract(
    profile: ModelProfile,
    api_key_env: str,
    api_key: str,
    model_override: str,
    base_url_override: str,
) -> None:
    completion = SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(
                    content=None,
                    tool_calls=(
                        SimpleNamespace(
                            id="call-provider",
                            function=SimpleNamespace(
                                name="get_product_history",
                                arguments='{"product_id":"P4711"}',
                            ),
                        ),
                    ),
                ),
                finish_reason="tool_calls",
            )
        ],
        usage=SimpleNamespace(prompt_tokens=11, completion_tokens=7, total_tokens=18),
    )
    fake_client = FakeOpenAIClient(completion)
    client_arguments: dict[str, object] = {}
    environment = {
        api_key_env: api_key,
        f"{api_key_env.removesuffix('_API_KEY')}_MODEL": model_override,
        f"{api_key_env.removesuffix('_API_KEY')}_BASE_URL": base_url_override,
    }
    client = OpenAICompatibleLLMClient(
        load_llm_configuration(PROJECT_ROOT / "config" / "model_catalog.toml"),
        environment=environment,
        client_factory=lambda **kwargs: client_arguments.update(kwargs) or fake_client,
    )
    request = LLMRequest(
        messages=(LLMMessage(role=MessageRole.USER, content="Inspect P4711"),),
        tools=(
            LLMToolDefinition(
                name="get_product_history",
                description="Get the production history for a product.",
                parameters={"type": "object"},
            ),
        ),
    )

    response = client.chat(profile, request)

    assert client_arguments == {
        "api_key": api_key,
        "base_url": base_url_override,
        "max_retries": 0,
        "timeout": 45.0,
    }
    assert fake_client.completions.parameters is not None
    assert fake_client.completions.parameters["model"] == model_override
    assert fake_client.completions.parameters["parallel_tool_calls"] is False
    assert response.tool_calls == (
        LLMToolCall(
            id="call-provider",
            name="get_product_history",
            arguments={"product_id": "P4711"},
        ),
    )
    assert response.usage is not None
    assert response.usage.input_tokens == 11
    assert response.usage.output_tokens == 7
    assert response.usage.total_tokens == 18


def test_nvidia_profile_uses_the_existing_structured_output_contract() -> None:
    completion = SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(
                    content='{"status":"ok","provider":"nvidia"}', tool_calls=None
                ),
                finish_reason="stop",
            )
        ]
    )
    fake_client = FakeOpenAIClient(completion)
    client = OpenAICompatibleLLMClient(
        load_llm_configuration(PROJECT_ROOT / "config" / "model_catalog.toml"),
        environment={"NVIDIA_API_KEY": "nvidia-test-key"},
        client_factory=lambda **_: fake_client,
    )
    request = LLMRequest(
        messages=(
            LLMMessage(role=MessageRole.USER, content="Return structured output"),
        ),
        response_format=LLMResponseFormat(
            json_schema=LLMJsonSchema(
                name="provider_probe",
                schema_definition={"type": "object", "additionalProperties": False},
            )
        ),
    )

    response = client.chat(NVIDIA_QUALITY_PROFILE, request)

    assert response.text == '{"status":"ok","provider":"nvidia"}'
    assert fake_client.completions.parameters is not None
    assert fake_client.completions.parameters["response_format"] == (
        request.response_format.model_dump(mode="json", by_alias=True)
    )
    assert fake_client.completions.parameters["max_tokens"] == 256


def test_groq_strict_response_schema_requires_defaulted_object_properties() -> None:
    completion = SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(content='{"status":"ok"}', tool_calls=None),
                finish_reason="stop",
            )
        ]
    )
    fake_client = FakeOpenAIClient(completion)
    configuration = load_llm_configuration(
        PROJECT_ROOT / "config" / "model_catalog.toml"
    )
    request = LLMRequest(
        messages=(
            LLMMessage(role=MessageRole.USER, content="Return structured output"),
        ),
        response_format=LLMResponseFormat(
            json_schema=LLMJsonSchema(
                name="provider_probe",
                schema_definition={
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "format": {"type": "string", "default": "document"},
                    },
                    "required": ["name"],
                    "additionalProperties": False,
                },
            )
        ),
    )
    client = OpenAICompatibleLLMClient(
        configuration,
        environment={"GROQ_API_KEY": "groq-test-key"},
        client_factory=lambda **_: fake_client,
    )

    client.chat(GROQ_BENCHMARK_PROFILE, request)

    assert fake_client.completions.parameters is not None
    schema = fake_client.completions.parameters["response_format"]["json_schema"][
        "schema"
    ]
    assert schema["required"] == ["name", "format"]
    assert request.response_format.json_schema.schema_definition["required"] == ["name"]


def test_groq_structured_output_records_content_free_request_diagnostics() -> None:
    completion = SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(content='{"status":"ok"}', tool_calls=None),
                finish_reason="stop",
            )
        ]
    )
    request = _structured_request("private prompt and tool result must not appear")
    client = OpenAICompatibleLLMClient(
        load_llm_configuration(PROJECT_ROOT / "config" / "model_catalog.toml"),
        environment={"GROQ_API_KEY": "groq-test-key"},
        client_factory=lambda **_: FakeOpenAIClient(completion),
    )

    response = client.chat(GROQ_BENCHMARK_PROFILE, request)

    assert response.request_diagnostics is not None
    diagnostics = response.request_diagnostics.model_dump()
    assert diagnostics["request_payload_bytes"] > 0
    assert diagnostics["message_count"] == 1
    assert diagnostics["tool_definition_count"] == 0
    assert diagnostics["has_tools"] is False
    assert diagnostics["has_structured_output"] is True
    assert diagnostics["structured_schema_hash"].startswith("sha256:")
    assert "private prompt" not in str(diagnostics)
    assert "tool result" not in str(diagnostics)


def test_schema_fingerprint_is_stable_for_content_changes_and_changes_for_schema() -> (
    None
):
    configuration = load_llm_configuration(
        PROJECT_ROOT / "config" / "model_catalog.toml"
    )

    def request_hash(request: LLMRequest) -> str:
        client = OpenAICompatibleLLMClient(
            configuration,
            environment={"GROQ_API_KEY": "groq-test-key"},
            client_factory=lambda **_: FakeOpenAIClient(
                SimpleNamespace(
                    choices=[
                        SimpleNamespace(
                            message=SimpleNamespace(
                                content='{"status":"ok"}', tool_calls=None
                            ),
                            finish_reason="stop",
                        )
                    ]
                )
            ),
        )
        response = client.chat(GROQ_BENCHMARK_PROFILE, request)
        assert response.request_diagnostics is not None
        assert response.request_diagnostics.structured_schema_hash is not None
        return response.request_diagnostics.structured_schema_hash

    first = request_hash(_structured_request("first private prompt"))
    same_schema = request_hash(_structured_request("second private prompt"))
    changed_schema = request_hash(
        _structured_request(
            "third private prompt",
            schema={"type": "object", "properties": {"answer": {"type": "string"}}},
        )
    )

    assert first == same_schema
    assert first != changed_schema


def test_maps_assistant_tool_call_and_tool_result_messages() -> None:
    completion = SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(content="Final answer", tool_calls=None),
                finish_reason="stop",
            )
        ]
    )
    fake_client = FakeOpenAIClient(completion)
    client = OpenAICompatibleLLMClient(
        create_configuration(),
        environment={},
        client_factory=lambda **_: fake_client,
    )
    request = LLMRequest(
        messages=(
            LLMMessage(role=MessageRole.USER, content="Inspect P4711"),
            LLMMessage(
                role=MessageRole.ASSISTANT,
                content=None,
                tool_calls=(
                    LLMToolCall(
                        id="call-1",
                        name="get_product_history",
                        arguments={"product_id": "P4711"},
                    ),
                ),
            ),
            LLMMessage(
                role=MessageRole.TOOL,
                content='{"product_id":"P4711","found":true,"steps":[]}',
                tool_call_id="call-1",
            ),
        )
    )

    client.chat(LOCAL_QUALITY_PROFILE, request)

    assert fake_client.completions.parameters is not None
    messages = fake_client.completions.parameters["messages"]
    assert messages[1] == {
        "role": "assistant",
        "content": None,
        "tool_calls": [
            {
                "id": "call-1",
                "type": "function",
                "function": {
                    "name": "get_product_history",
                    "arguments": '{"product_id": "P4711"}',
                },
            }
        ],
    }
    assert messages[2] == {
        "role": "tool",
        "content": '{"product_id":"P4711","found":true,"steps":[]}',
        "tool_call_id": "call-1",
    }


def test_requires_api_key_from_configured_environment_variable() -> None:
    client = OpenAICompatibleLLMClient(
        create_authenticated_configuration(),
        environment={},
        client_factory=lambda **_: pytest.fail("client factory must not be called"),
    )
    request = LLMRequest(messages=(LLMMessage(role=MessageRole.USER, content="Hello"),))

    with pytest.raises(
        ValueError,
        match="Missing API key environment variable: CLOUD_LLM_API_KEY",
    ):
        client.chat(LOCAL_QUALITY_PROFILE, request)


def test_explicit_groq_benchmark_rejects_missing_api_key_without_network_call() -> None:
    configuration = load_llm_configuration(
        PROJECT_ROOT / "config" / "model_catalog.toml"
    )
    client = OpenAICompatibleLLMClient(
        configuration,
        environment={},
        client_factory=lambda **_: pytest.fail("client factory must not be called"),
    )
    request = LLMRequest(
        messages=(LLMMessage(role=MessageRole.USER, content="PUBLIC_LLM_OK"),)
    )

    with pytest.raises(
        ValueError,
        match="Missing API key environment variable: GROQ_API_KEY",
    ):
        client.chat(GROQ_BENCHMARK_PROFILE, request)


def test_reads_authenticated_profile_api_key_from_environment_variable() -> None:
    completion = SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(content="Done", tool_calls=None),
                finish_reason="stop",
            )
        ]
    )
    fake_client = FakeOpenAIClient(completion)
    factory_arguments: dict[str, str] = {}

    def client_factory(**arguments: str) -> FakeOpenAIClient:
        factory_arguments.update(arguments)
        return fake_client

    client = OpenAICompatibleLLMClient(
        create_authenticated_configuration(),
        environment={"CLOUD_LLM_API_KEY": "test-api-key-from-environment"},
        client_factory=client_factory,
    )
    request = LLMRequest(messages=(LLMMessage(role=MessageRole.USER, content="Hello"),))

    client.chat(LOCAL_QUALITY_PROFILE, request)

    assert factory_arguments == {
        "api_key": "test-api-key-from-environment",
        "base_url": "https://llm.example.com/v1",
        "max_retries": 0,
        "timeout": 45.0,
    }


def test_maps_unknown_finish_reason() -> None:
    completion = SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(content="Done", tool_calls=None),
                finish_reason="provider_specific_reason",
            )
        ]
    )
    fake_client = FakeOpenAIClient(completion)
    client = OpenAICompatibleLLMClient(
        create_configuration(),
        environment={},
        client_factory=lambda **_: fake_client,
    )
    request = LLMRequest(messages=(LLMMessage(role=MessageRole.USER, content="Hello"),))

    response = client.chat(LOCAL_QUALITY_PROFILE, request)

    assert response.finish_reason is FinishReason.UNKNOWN


def test_maps_provider_reported_usage_without_estimation() -> None:
    completion = SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(content="Done", tool_calls=None),
                finish_reason="stop",
            )
        ],
        usage=SimpleNamespace(
            prompt_tokens=12,
            completion_tokens=8,
            total_tokens=20,
        ),
    )
    client = OpenAICompatibleLLMClient(
        create_configuration(),
        environment={},
        client_factory=lambda **_: FakeOpenAIClient(completion),
    )

    response = client.chat(
        LOCAL_QUALITY_PROFILE,
        LLMRequest(messages=(LLMMessage(role=MessageRole.USER, content="Hello"),)),
    )

    assert response.usage is not None
    assert response.usage.input_tokens == 12
    assert response.usage.output_tokens == 8
    assert response.usage.total_tokens == 20


def test_keeps_usage_unavailable_when_provider_does_not_supply_it() -> None:
    completion = SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(content="Done", tool_calls=None),
                finish_reason="stop",
            )
        ]
    )
    client = OpenAICompatibleLLMClient(
        create_configuration(),
        environment={},
        client_factory=lambda **_: FakeOpenAIClient(completion),
    )

    response = client.chat(
        LOCAL_QUALITY_PROFILE,
        LLMRequest(messages=(LLMMessage(role=MessageRole.USER, content="Hello"),)),
    )

    assert response.usage is None


def test_ignores_malformed_provider_usage_without_failing_response() -> None:
    completion = SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(content="Done", tool_calls=None),
                finish_reason="stop",
            )
        ],
        usage=SimpleNamespace(
            prompt_tokens="invalid",
            completion_tokens=-1,
            total_tokens=True,
        ),
    )
    client = OpenAICompatibleLLMClient(
        create_configuration(),
        environment={},
        client_factory=lambda **_: FakeOpenAIClient(completion),
    )

    response = client.chat(
        LOCAL_QUALITY_PROFILE,
        LLMRequest(messages=(LLMMessage(role=MessageRole.USER, content="Hello"),)),
    )

    assert response.text == "Done"
    assert response.usage is None


def test_rejects_non_object_tool_call_arguments() -> None:
    completion = SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(
                    content=None,
                    tool_calls=[
                        SimpleNamespace(
                            id="call-1",
                            function=SimpleNamespace(
                                name="get_product_history",
                                arguments='["P4711"]',
                            ),
                        )
                    ],
                ),
                finish_reason="tool_calls",
            )
        ]
    )
    fake_client = FakeOpenAIClient(completion)
    client = OpenAICompatibleLLMClient(
        create_configuration(),
        environment={},
        client_factory=lambda **_: fake_client,
    )
    request = LLMRequest(messages=(LLMMessage(role=MessageRole.USER, content="Hello"),))

    with pytest.raises(TypeError, match="arguments must be a JSON object"):
        client.chat(LOCAL_QUALITY_PROFILE, request)


def test_classifies_openai_rate_limit_without_exposing_provider_message() -> None:
    provider_error = RateLimitError(
        "account key secret and retry details",
        response=_provider_response(429),
        body={"error": {"code": "rate_limit_exceeded"}},
    )
    client = OpenAICompatibleLLMClient(
        create_configuration(),
        environment={},
        client_factory=lambda **_: FakeOpenAIClient(provider_error),
    )

    with pytest.raises(LLMProviderError) as raised:
        client.chat(
            LOCAL_QUALITY_PROFILE,
            LLMRequest(messages=(LLMMessage(role=MessageRole.USER, content="Hello"),)),
        )

    assert raised.value.code == LLMProviderErrorCode.RATE_LIMIT.value
    assert raised.value.provider_error_type == "RateLimitError"
    assert "secret" not in str(raised.value)


def test_classifies_bad_provider_request_without_exposing_provider_message() -> None:
    provider_error = BadRequestError(
        "provider protocol detail must remain private",
        response=_provider_response(400, headers={"x-request-id": "groq-safe-123"}),
        body={
            "error": {
                "code": "invalid_request_error",
                "message": "invalid JSON schema for response_format: private",
            }
        },
    )
    client = OpenAICompatibleLLMClient(
        create_configuration(supports_structured_output=True, provider="groq"),
        environment={},
        client_factory=lambda **_: FakeOpenAIClient(provider_error),
    )

    with pytest.raises(LLMProviderError) as raised:
        client.chat(
            LOCAL_QUALITY_PROFILE,
            _structured_request("private prompt that must not be diagnosed"),
        )

    assert raised.value.code == LLMProviderErrorCode.REQUEST_INVALID.value
    assert raised.value.provider_error_type == "BadRequestError"
    assert raised.value.provider_request_reason == "invalid_response_schema"
    assert raised.value.provider_http_status == 400
    assert raised.value.provider_error_category == "invalid_request_error"
    assert raised.value.provider_request_id == "groq-safe-123"
    assert raised.value.request_diagnostics is not None
    assert raised.value.request_diagnostics.request_payload_bytes > 0
    assert raised.value.request_diagnostics.structured_schema_hash is not None
    assert "private" not in str(raised.value)


def test_classifies_known_quota_code_before_rate_limit() -> None:
    provider_error = RateLimitError(
        "quota detail must remain private",
        response=_provider_response(429),
        body={"error": {"type": "insufficient_quota"}},
    )
    client = OpenAICompatibleLLMClient(
        create_configuration(),
        environment={},
        client_factory=lambda **_: FakeOpenAIClient(provider_error),
    )

    with pytest.raises(LLMProviderError) as raised:
        client.chat(
            LOCAL_QUALITY_PROFILE,
            LLMRequest(messages=(LLMMessage(role=MessageRole.USER, content="Hello"),)),
        )

    assert raised.value.code == LLMProviderErrorCode.QUOTA_EXCEEDED.value


def test_does_not_classify_unrecognized_provider_http_429_as_rate_limit() -> None:
    provider_error = APIStatusError(
        "unrelated provider 429",
        response=_provider_response(429),
        body={"error": {"code": "unrecognized_429"}},
    )
    client = OpenAICompatibleLLMClient(
        create_configuration(),
        environment={},
        client_factory=lambda **_: FakeOpenAIClient(provider_error),
    )

    with pytest.raises(APIStatusError):
        client.chat(
            LOCAL_QUALITY_PROFILE,
            LLMRequest(messages=(LLMMessage(role=MessageRole.USER, content="Hello"),)),
        )


def test_classifies_known_provider_maintenance_status_as_unavailable() -> None:
    provider_error = APIStatusError(
        "provider maintenance details",
        response=_provider_response(503),
        body=None,
    )
    client = OpenAICompatibleLLMClient(
        create_configuration(),
        environment={},
        client_factory=lambda **_: FakeOpenAIClient(provider_error),
    )

    with pytest.raises(LLMProviderError) as raised:
        client.chat(
            LOCAL_QUALITY_PROFILE,
            LLMRequest(messages=(LLMMessage(role=MessageRole.USER, content="Hello"),)),
        )

    assert raised.value.code == LLMProviderErrorCode.PROVIDER_UNAVAILABLE.value


def test_closes_created_clients() -> None:
    completion = SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(content="Done", tool_calls=None),
                finish_reason="stop",
            )
        ]
    )
    fake_client = FakeOpenAIClient(completion)
    client = OpenAICompatibleLLMClient(
        create_configuration(),
        environment={},
        client_factory=lambda **_: fake_client,
    )
    request = LLMRequest(messages=(LLMMessage(role=MessageRole.USER, content="Hello"),))
    client.chat(LOCAL_QUALITY_PROFILE, request)

    client.close()

    assert fake_client.closed is True


def _structured_request(
    content: str,
    *,
    schema: dict[str, object] | None = None,
) -> LLMRequest:
    return LLMRequest(
        messages=(LLMMessage(role=MessageRole.USER, content=content),),
        response_format=LLMResponseFormat(
            json_schema=LLMJsonSchema(
                name="provider_probe",
                schema_definition=schema
                or {
                    "type": "object",
                    "properties": {"status": {"type": "string"}},
                    "additionalProperties": False,
                },
            )
        ),
    )


def _provider_response(
    status_code: int, *, headers: dict[str, str] | None = None
) -> httpx.Response:
    return httpx.Response(
        status_code,
        request=httpx.Request("POST", "https://provider.example.test/v1/chat"),
        headers=headers,
    )

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from industrial_ai_agent.agent.llm import (
    FinishReason,
    LLMMessage,
    LLMRequest,
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
TROUBLESHOOTING_PROFILE = ModelProfile("troubleshooting")
PUBLIC_FAST_PROFILE = ModelProfile("public_fast")


class FakeCompletions:
    def __init__(self, completion: SimpleNamespace) -> None:
        self.completion = completion
        self.parameters: dict[str, Any] | None = None

    def create(self, **parameters: Any) -> SimpleNamespace:
        self.parameters = parameters
        return self.completion


class FakeOpenAIClient:
    def __init__(self, completion: SimpleNamespace) -> None:
        self.completions = FakeCompletions(completion)
        self.chat = SimpleNamespace(completions=self.completions)
        self.closed = False

    def close(self) -> None:
        self.closed = True


def create_configuration() -> LLMConfiguration:
    return LLMConfiguration.model_validate(
        {
            "profiles": {
                "troubleshooting": {
                    "provider": "ollama",
                    "model": "qwen3.5:9b",
                    "base_url": "http://localhost:11434/v1",
                    "temperature": 0,
                    "authentication": "none",
                    "execution_zone": "LOCAL",
                    "capabilities": ["TEXT", "TOOL_CALLING"],
                    "quality_class": "HIGH",
                    "cost_class": "LOW",
                }
            }
        }
    )


def create_authenticated_configuration() -> LLMConfiguration:
    return LLMConfiguration.model_validate(
        {
            "profiles": {
                "troubleshooting": {
                    "provider": "cloud-provider",
                    "model": "cloud-model",
                    "base_url": "https://llm.example.com/v1",
                    "temperature": 0,
                    "authentication": "api_key",
                    "api_key_env": "CLOUD_LLM_API_KEY",
                    "execution_zone": "PUBLIC_CLOUD",
                    "capabilities": ["TEXT"],
                    "quality_class": "HIGH",
                    "cost_class": "LOW",
                }
            }
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

    response = client.chat(TROUBLESHOOTING_PROFILE, request)

    assert factory_arguments == {
        "api_key": "not-used",
        "base_url": "http://localhost:11434/v1",
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

    response = client.chat(TROUBLESHOOTING_PROFILE, request)

    assert response.text is None
    assert response.finish_reason is FinishReason.TOOL_CALLS
    assert response.tool_calls[0].name == "get_product_history"
    assert response.tool_calls[0].arguments == {"product_id": "P4711"}
    assert fake_client.completions.parameters is not None
    assert fake_client.completions.parameters["tools"][0]["function"]["name"] == (
        "get_product_history"
    )
    assert fake_client.completions.parameters["parallel_tool_calls"] is False


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

    client.chat(TROUBLESHOOTING_PROFILE, request)

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
        client.chat(TROUBLESHOOTING_PROFILE, request)


def test_public_fast_rejects_missing_groq_api_key_without_network_call() -> None:
    configuration = load_llm_configuration(
        PROJECT_ROOT / "config" / "model_profiles.toml"
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
        client.chat(PUBLIC_FAST_PROFILE, request)


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

    client.chat(TROUBLESHOOTING_PROFILE, request)

    assert factory_arguments == {
        "api_key": "test-api-key-from-environment",
        "base_url": "https://llm.example.com/v1",
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

    response = client.chat(TROUBLESHOOTING_PROFILE, request)

    assert response.finish_reason is FinishReason.UNKNOWN


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
        client.chat(TROUBLESHOOTING_PROFILE, request)


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
    client.chat(TROUBLESHOOTING_PROFILE, request)

    client.close()

    assert fake_client.closed is True

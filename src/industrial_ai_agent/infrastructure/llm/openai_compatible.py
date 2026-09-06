import json
import os
from collections.abc import Callable, Mapping
from typing import Any, Self

from openai import OpenAI

from industrial_ai_agent.agent.llm import (
    FinishReason,
    LLMMessage,
    LLMRequest,
    LLMResponse,
    LLMToolCall,
    LLMUsage,
    ModelProfile,
)
from industrial_ai_agent.infrastructure.llm.configuration import (
    AuthenticationMode,
    LLMConfiguration,
    ModelProfileConfig,
)

_FINISH_REASONS = {
    "stop": FinishReason.STOP,
    "length": FinishReason.LENGTH,
    "tool_calls": FinishReason.TOOL_CALLS,
    "content_filter": FinishReason.CONTENT_FILTER,
}
_NO_AUTH_SDK_API_KEY = "not-used"


class OpenAICompatibleLLMClient:
    def __init__(
        self,
        configuration: LLMConfiguration,
        *,
        environment: Mapping[str, str] | None = None,
        client_factory: Callable[..., Any] = OpenAI,
    ) -> None:
        self._configuration = configuration
        self._environment = environment if environment is not None else os.environ
        self._client_factory = client_factory
        self._clients: dict[str, Any] = {}

    def chat(self, profile: ModelProfile, request: LLMRequest) -> LLMResponse:
        profile_config = self._configuration.get_profile(profile.name)
        client = self._get_client(profile)
        parameters: dict[str, Any] = {
            "model": profile_config.model,
            "messages": [_serialize_message(message) for message in request.messages],
            "temperature": profile_config.temperature,
        }
        if request.tools:
            parameters["tools"] = [
                {
                    "type": "function",
                    "function": {
                        "name": tool.name,
                        "description": tool.description,
                        "parameters": tool.parameters,
                    },
                }
                for tool in request.tools
            ]
            # The bounded ADR-004 loop accepts exactly one next tool decision.
            parameters["parallel_tool_calls"] = False
        if request.response_format is not None:
            if not profile_config.supports_structured_output:
                raise ValueError(
                    "Model profile does not support structured response output"
                )
            parameters["response_format"] = request.response_format.model_dump(
                mode="json", by_alias=True
            )
        if request.reasoning_effort is not None:
            if not profile_config.supports_reasoning_effort:
                raise ValueError(
                    "Model profile does not support reasoning-effort control"
                )
            parameters["reasoning_effort"] = request.reasoning_effort.value

        completion = client.chat.completions.create(**parameters)
        if not completion.choices:
            raise ValueError("LLM response did not contain a choice")

        choice = completion.choices[0]
        return LLMResponse(
            text=choice.message.content,
            tool_calls=tuple(
                _parse_tool_call(tool_call)
                for tool_call in (choice.message.tool_calls or ())
            ),
            finish_reason=_FINISH_REASONS.get(
                choice.finish_reason,
                FinishReason.UNKNOWN,
            ),
            usage=_parse_usage(getattr(completion, "usage", None)),
        )

    def close(self) -> None:
        for client in self._clients.values():
            client.close()
        self._clients.clear()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def _get_client(self, profile: ModelProfile) -> Any:
        if profile.name not in self._clients:
            profile_config = self._configuration.get_profile(profile.name)
            self._clients[profile.name] = self._client_factory(
                api_key=self._resolve_api_key(profile_config),
                base_url=str(profile_config.base_url),
            )
        return self._clients[profile.name]

    def _resolve_api_key(self, profile_config: ModelProfileConfig) -> str:
        if profile_config.authentication is AuthenticationMode.NONE:
            return _NO_AUTH_SDK_API_KEY

        api_key_env = profile_config.api_key_env
        if api_key_env is None:
            raise ValueError("Authenticated model profile is missing api_key_env")
        api_key = self._environment.get(api_key_env)
        if not api_key:
            raise ValueError(f"Missing API key environment variable: {api_key_env}")
        return api_key


def _parse_tool_call(tool_call: Any) -> LLMToolCall:
    arguments = json.loads(tool_call.function.arguments)
    if not isinstance(arguments, dict):
        raise TypeError("LLM tool-call arguments must be a JSON object")
    return LLMToolCall(
        id=tool_call.id,
        name=tool_call.function.name,
        arguments=arguments,
    )


def _parse_usage(usage: Any) -> LLMUsage | None:
    """Map only token counts supplied by an OpenAI-compatible provider."""
    if usage is None:
        return None
    input_tokens = _token_count(usage, "prompt_tokens")
    output_tokens = _token_count(usage, "completion_tokens")
    total_tokens = _token_count(usage, "total_tokens")
    if input_tokens is None and output_tokens is None and total_tokens is None:
        return None
    return LLMUsage(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=total_tokens,
    )


def _token_count(usage: Any, name: str) -> int | None:
    value = getattr(usage, name, None)
    return (
        value
        if isinstance(value, int) and not isinstance(value, bool) and value >= 0
        else None
    )


def _serialize_message(message: LLMMessage) -> dict[str, Any]:
    serialized: dict[str, Any] = {
        "role": message.role.value,
        "content": message.content,
    }
    if message.tool_calls:
        serialized["tool_calls"] = [
            {
                "id": tool_call.id,
                "type": "function",
                "function": {
                    "name": tool_call.name,
                    "arguments": json.dumps(tool_call.arguments),
                },
            }
            for tool_call in message.tool_calls
        ]
    if message.tool_call_id:
        serialized["tool_call_id"] = message.tool_call_id
    return serialized

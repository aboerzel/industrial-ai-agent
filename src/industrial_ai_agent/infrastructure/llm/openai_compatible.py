import json
import os
from collections.abc import Callable, Mapping
from typing import Any, Self

from openai import APIConnectionError, APIStatusError, OpenAI, RateLimitError
from pydantic import BaseModel

from industrial_ai_agent.agent.llm import (
    FinishReason,
    LLMMessage,
    LLMProviderError,
    LLMProviderErrorCode,
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
_SDK_MAX_RETRIES = 0
_RATE_LIMIT_CODES = frozenset({"rate_limit_exceeded", "rate_limited"})
_QUOTA_CODES = frozenset(
    {
        "insufficient_quota",
        "quota_exceeded",
        "quota_exhausted",
        "daily_token_limit_exceeded",
        "daily_tokens_exceeded",
        "token_limit_exceeded",
        "tokens_limit_exceeded",
        "tokens_limit_reached",
    }
)
_PROVIDER_UNAVAILABLE_STATUS_CODES = frozenset({502, 503, 504})


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
            "model": _resolve_configured_value(
                profile_config.model, profile_config.model_env, self._environment
            ),
            "messages": [_serialize_message(message) for message in request.messages],
            "temperature": profile_config.temperature,
        }
        if profile_config.max_output_tokens is not None:
            parameters["max_tokens"] = profile_config.max_output_tokens
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
            # Ollama's OpenAI-compatible endpoint accepts the documented
            # ``reasoning_effort`` field. Sending native ``think`` through
            # ``extra_body`` leaves Qwen thinking enabled on this endpoint.
            parameters["reasoning_effort"] = request.reasoning_effort.value

        try:
            completion = client.chat.completions.create(**parameters)
        except Exception as error:
            classified = _classify_provider_error(error)
            if classified is not None:
                raise LLMProviderError(
                    classified,
                    provider_error_type=type(error).__name__,
                ) from error
            raise
        if not completion.choices:
            raise ValueError("LLM response did not contain a choice")

        choice = completion.choices[0]
        return LLMResponse(
            text=_response_text(
                choice.message,
                structured_output=request.response_format is not None,
            ),
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
                base_url=_resolve_configured_value(
                    str(profile_config.base_url),
                    profile_config.base_url_env,
                    self._environment,
                ),
                # Let the application classify a provider limit immediately. The
                # OpenAI SDK otherwise retries 429 responses with backoff inside
                # the bounded Agent execution deadline.
                max_retries=_SDK_MAX_RETRIES,
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


def _resolve_configured_value(
    default: str, environment_variable: str | None, environment: Mapping[str, str]
) -> str:
    """Prefer a non-empty deployment override while retaining a validated default."""
    if environment_variable:
        value = environment.get(environment_variable, "").strip()
        if value:
            return value
    return default


def _response_text(message: Any, *, structured_output: bool) -> str | None:
    """Normalize documented OpenAI-compatible response content representations."""
    parsed = getattr(message, "parsed", None)
    if parsed is not None:
        return _serialized_structured_content(parsed)

    content = getattr(message, "content", None)
    if content is None or isinstance(content, str):
        return content
    if isinstance(content, list):
        return _text_blocks_content(content)
    if structured_output and isinstance(content, Mapping):
        return _serialized_structured_content(content)
    raise TypeError("LLM response content must be text or documented text blocks")


def _serialized_structured_content(content: object) -> str:
    if isinstance(content, BaseModel):
        content = content.model_dump(mode="json")
    if not isinstance(content, Mapping):
        raise TypeError("Parsed structured LLM response must be an object")
    return json.dumps(content, ensure_ascii=False, separators=(",", ":"))


def _text_blocks_content(content: list[object]) -> str:
    blocks: list[str] = []
    for block in content:
        if not isinstance(block, Mapping) or block.get("type") != "text":
            raise TypeError("LLM response content blocks must be text blocks")
        text = block.get("text")
        if not isinstance(text, str):
            raise TypeError("LLM response text block must contain text")
        blocks.append(text)
    return "".join(blocks)


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


def _classify_provider_error(error: Exception) -> LLMProviderErrorCode | None:
    """Classify only recognized failures raised by this provider SDK boundary."""
    codes = _provider_error_codes(error)
    if codes & _QUOTA_CODES:
        return LLMProviderErrorCode.QUOTA_EXCEEDED
    if isinstance(error, RateLimitError):
        return LLMProviderErrorCode.RATE_LIMIT
    if codes & _RATE_LIMIT_CODES:
        return LLMProviderErrorCode.RATE_LIMIT
    if isinstance(error, APIConnectionError):
        return LLMProviderErrorCode.PROVIDER_UNAVAILABLE
    if (
        isinstance(error, APIStatusError)
        and error.status_code in _PROVIDER_UNAVAILABLE_STATUS_CODES
    ):
        return LLMProviderErrorCode.PROVIDER_UNAVAILABLE
    return None


def _provider_error_codes(error: Exception) -> frozenset[str]:
    """Read documented structured SDK fields, never free-text provider messages."""
    values: list[object] = [getattr(error, "code", None), getattr(error, "type", None)]
    body = getattr(error, "body", None)
    if isinstance(body, Mapping):
        values.extend((body.get("code"), body.get("type")))
        nested_error = body.get("error")
        if isinstance(nested_error, Mapping):
            values.extend((nested_error.get("code"), nested_error.get("type")))
    return frozenset(
        value.strip().casefold()
        for value in values
        if isinstance(value, str) and value.strip()
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

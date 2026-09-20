"""Focused readiness and reconnect regressions for configured MCP servers."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest

from industrial_ai_agent.agent.mcp_tool_provider import McpToolSession
from industrial_ai_agent.agent.troubleshooting_run_service import (
    McpServiceUnavailableError,
)
from industrial_ai_agent.infrastructure.factory_mcp_client import (
    StreamableHttpServerParameters,
)
from industrial_ai_agent.infrastructure.mcp_langchain_tool_provider import (
    McpLangChainToolProvider,
)
from industrial_ai_agent.infrastructure.mcp_readiness import (
    McpReadinessError,
    probe_mcp_readiness,
)


class _FakeMcpSession:
    def __init__(self, tool_names: tuple[str, ...]) -> None:
        self._tool_names = tool_names

    async def initialize(self):
        return SimpleNamespace(server_info=SimpleNamespace(name="knowledge"))

    async def list_tools(self):
        return SimpleNamespace(
            tools=tuple(SimpleNamespace(name=name) for name in self._tool_names)
        )


def test_protocol_readiness_requires_initialized_expected_capabilities(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    @asynccontextmanager
    async def open_ready_session(_transport) -> AsyncIterator[_FakeMcpSession]:
        yield _FakeMcpSession(("search_documentation",))

    monkeypatch.setattr(
        "industrial_ai_agent.infrastructure.mcp_readiness.open_mcp_session",
        open_ready_session,
    )

    result = asyncio.run(
        probe_mcp_readiness(
            StreamableHttpServerParameters(url="http://knowledge.invalid/mcp"),
            required_tool_names=("search_documentation",),
        )
    )

    assert result.server_name == "knowledge"
    assert result.tool_names == ("search_documentation",)


def test_protocol_readiness_rejects_process_without_required_capability(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    @asynccontextmanager
    async def open_incomplete_session(_transport) -> AsyncIterator[_FakeMcpSession]:
        yield _FakeMcpSession(())

    monkeypatch.setattr(
        "industrial_ai_agent.infrastructure.mcp_readiness.open_mcp_session",
        open_incomplete_session,
    )

    with pytest.raises(McpReadinessError, match="Required MCP capabilities"):
        asyncio.run(
            probe_mcp_readiness(
                StreamableHttpServerParameters(url="http://knowledge.invalid/mcp"),
                required_tool_names=("search_documentation",),
            )
        )


class _TransientDiscoveryProvider(McpLangChainToolProvider):
    def __init__(self, outcomes: list[bool]) -> None:
        super().__init__(
            StreamableHttpServerParameters(url="http://knowledge.invalid/mcp"),
            discovery_retry_delays_seconds=(0.0, 0.0),
        )
        self.outcomes = outcomes
        self.attempts = 0

    @asynccontextmanager
    async def _open_session_once(self) -> AsyncIterator[McpToolSession]:
        self.attempts += 1
        if not self.outcomes.pop(0):
            error = McpServiceUnavailableError("MCP service is unavailable")
            error.mcp_server_id = "knowledge"
            raise error
        yield McpToolSession(
            tools=(),
            discovered_tool_names=(),
            server_name="knowledge",
            server_version="1",
            protocol_version="1",
        )


def test_transient_discovery_recovers_without_restarting_agent_api() -> None:
    provider = _TransientDiscoveryProvider([False, True])

    async def open_session() -> str:
        async with provider.open_session() as session:
            return session.server_name

    assert asyncio.run(open_session()) == "knowledge"
    assert provider.attempts == 2


def test_persistent_discovery_failure_is_sanitized_after_bounded_retries() -> None:
    provider = _TransientDiscoveryProvider([False, False, False])

    async def open_session() -> None:
        async with provider.open_session():
            pass

    with pytest.raises(McpServiceUnavailableError, match="MCP service is unavailable"):
        asyncio.run(open_session())
    assert provider.attempts == 3


def test_already_ready_discovery_does_not_retry() -> None:
    provider = _TransientDiscoveryProvider([True])

    async def open_session() -> None:
        async with provider.open_session():
            pass

    asyncio.run(open_session())
    assert provider.attempts == 1


def test_later_run_recovers_after_an_mcp_restart_without_agent_restart() -> None:
    provider = _TransientDiscoveryProvider([True, False, True])

    async def open_twice() -> None:
        async with provider.open_session():
            pass
        async with provider.open_session():
            pass

    asyncio.run(open_twice())
    assert provider.attempts == 3


class _ClosableMcpSession:
    async def initialize(self):
        return SimpleNamespace(
            server_info=SimpleNamespace(name="factory", version="1"),
            protocol_version="2025-06-18",
        )

    async def list_tools(self):
        return SimpleNamespace(
            tools=(
                SimpleNamespace(
                    name="get_machine_status",
                    description="Get machine status.",
                    input_schema={
                        "type": "object",
                        "properties": {
                            "station_id": {
                                "type": "string",
                                "minLength": 1,
                                "maxLength": 32,
                            }
                        },
                        "required": ["station_id"],
                        "additionalProperties": False,
                    },
                ),
            )
        )


@pytest.mark.parametrize(
    "consumer_error",
    (None, RuntimeError("model execution failed"), asyncio.CancelledError()),
)
def test_mcp_provider_closes_eval_owned_sessions_after_success_exception_and_cancellation(
    monkeypatch: pytest.MonkeyPatch,
    consumer_error: BaseException | None,
) -> None:
    closed: list[bool] = []

    @asynccontextmanager
    async def open_closable_session(_transport, *, telemetry=None):
        del telemetry
        try:
            yield _ClosableMcpSession()
        finally:
            closed.append(True)

    monkeypatch.setattr(
        "industrial_ai_agent.infrastructure.mcp_langchain_tool_provider.open_mcp_session",
        open_closable_session,
    )
    provider = McpLangChainToolProvider(
        StreamableHttpServerParameters(url="http://factory.invalid/mcp"),
        allowed_tool_names=frozenset({"get_machine_status"}),
    )

    async def consume_session() -> None:
        async with provider.open_session():
            if consumer_error is not None:
                raise consumer_error

    if consumer_error is not None:
        error_type = type(consumer_error)
        if error_type is RuntimeError:
            with pytest.raises(RuntimeError, match="model execution failed"):
                asyncio.run(consume_session())
        elif error_type is asyncio.CancelledError:
            with pytest.raises(asyncio.CancelledError):
                asyncio.run(consume_session())
        else:
            raise AssertionError("Unexpected test error type")
    else:
        asyncio.run(consume_session())

    assert closed == [True]

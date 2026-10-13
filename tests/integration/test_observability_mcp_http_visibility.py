"""Local HTTP transport regression; no external telemetry, database, or LLM."""

import asyncio
import os
import subprocess
import sys
from collections.abc import Iterator

import pytest
from test_secure_mcp_http_access import _free_port, _wait_for_listening_port

from industrial_ai_agent.infrastructure.factory_mcp_client import (
    StreamableHttpServerParameters,
    open_mcp_session,
)

_SOURCE = """
import os
import sys
sys.path.insert(0, 'tests/unit')
from test_observability_run_visibility import _setup
from industrial_ai_agent.domain.security import DataClassification
servers, backend, context, seen, store = _setup(
    DataClassification[os.environ['TEST_CLEARANCE']]
)
servers['observability'].run(
    transport='streamable-http', host='127.0.0.1',
    port=int(os.environ['TEST_MCP_PORT']), streamable_http_path='/mcp'
)
"""


@pytest.fixture(scope="module", params=["INTERNAL", "RESTRICTED"])
def observability_http(request) -> Iterator[tuple[str, str]]:
    port = _free_port()
    process = subprocess.Popen(
        [sys.executable, "-c", _SOURCE],
        env={**os.environ, "TEST_MCP_PORT": str(port), "TEST_CLEARANCE": request.param},
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        text=True,
    )
    try:
        _wait_for_listening_port(process, port)
        yield f"http://127.0.0.1:{port}/mcp", request.param
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


def test_http_protected_and_unknown_identifiers_are_indistinguishable(
    observability_http,
):
    url, clearance = observability_http

    async def verify():
        async with open_mcp_session(
            StreamableHttpServerParameters(
                url=url,
                bearer_token="visibility-test-token",
                request_headers={"X-Clearance": "RESTRICTED", "X-Client": "admin"},
            )
        ) as session:
            await session.initialize()
            for tool, key, accessible, protected, unknown in (
                (
                    "get_run_trace",
                    "run_id",
                    "123e4567-e89b-12d3-a456-426614174000",
                    "123e4567-e89b-12d3-a456-426614174001",
                    "123e4567-e89b-12d3-a456-426614174002",
                ),
                (
                    "investigate_run",
                    "run_id",
                    "123e4567-e89b-12d3-a456-426614174000",
                    "123e4567-e89b-12d3-a456-426614174001",
                    "123e4567-e89b-12d3-a456-426614174002",
                ),
                (
                    "get_run_metrics",
                    "run_or_trace_id",
                    "123e4567-e89b-12d3-a456-426614174000",
                    "123e4567-e89b-12d3-a456-426614174001",
                    "123e4567-e89b-12d3-a456-426614174002",
                ),
                (
                    "get_trace_logs",
                    "trace_id",
                    "0123456789abcdef0123456789abcdef",
                    "1123456789abcdef0123456789abcdef",
                    "2123456789abcdef0123456789abcdef",
                ),
                (
                    "get_run_metrics",
                    "run_or_trace_id",
                    "0123456789abcdef0123456789abcdef",
                    "1123456789abcdef0123456789abcdef",
                    "2123456789abcdef0123456789abcdef",
                ),
            ):
                allowed = await session.call_tool(tool, {key: accessible})
                assert not allowed.is_error
                hidden = await session.call_tool(tool, {key: protected})
                missing = await session.call_tool(tool, {key: unknown})
                assert missing.is_error
                if clearance == "INTERNAL":
                    assert hidden.is_error
                    assert hidden.model_dump() == missing.model_dump()
                    rendered = str(hidden.model_dump())
                    for value in (
                        protected,
                        unknown,
                        "RESTRICTED",
                        "span_count",
                        "duration",
                        "factory-mcp",
                        "trace_id",
                    ):
                        assert value not in rendered
                else:
                    assert not hidden.is_error
            health = await session.call_tool(
                "get_service_health", {"service_name": "runtime-mcp"}
            )
            assert not health.is_error

    asyncio.run(verify())

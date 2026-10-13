"""Wire-level action-approval regressions with memory-only repositories/devices."""

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
import asyncio
import os
import sys
from dataclasses import replace
sys.path.insert(0, 'tests/unit')
from test_protected_mcp_actions import _setup, _approve, RUN_ID
from industrial_ai_agent.domain.security import DataClassification
server, store, repo, device, context, seen = _setup(os.environ['TEST_KIND'])
asyncio.run(_approve(store, os.environ['TEST_KIND']))
record = asyncio.run(store.get(RUN_ID))
hidden_id = __import__('uuid').UUID('123e4567-e89b-12d3-a456-426614174001')
store._records[hidden_id] = replace(record, run_id=hidden_id, data_classification=DataClassification.RESTRICTED)
server.run(transport='streamable-http', host='127.0.0.1', port=int(os.environ['TEST_MCP_PORT']), streamable_http_path='/mcp')
"""


@pytest.fixture(scope="module", params=["factory", "hardware"])
def protected_server(request) -> Iterator[tuple[str, str]]:
    port = _free_port()
    process = subprocess.Popen(
        [sys.executable, "-c", _SOURCE],
        env={**os.environ, "TEST_MCP_PORT": str(port), "TEST_KIND": request.param},
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


def test_direct_http_requires_exact_approval_and_hides_other_action_state(
    protected_server,
):
    url, kind = protected_server
    tool = (
        "create_maintenance_ticket"
        if kind == "factory"
        else "execute_reference_calibration"
    )
    action_key = "request_id" if kind == "factory" else "action_id"
    arguments = {
        "run_id": "123e4567-e89b-12d3-a456-426614174000",
        "station_id": "S04",
        action_key: "ticket-call-1",
        **(
            {"summary": "Investigate QUALITY-09"}
            if kind == "factory"
            else {"device_id": "POSITION-ENC-02"}
        ),
    }

    async def verify():
        async with open_mcp_session(
            StreamableHttpServerParameters(url=url, bearer_token="action-test-token")
        ) as session:
            await session.initialize()
            wrong = await session.call_tool(
                tool, {**arguments, action_key: "unrelated-approval"}
            )
            hidden = await session.call_tool(
                tool, {**arguments, "run_id": "123e4567-e89b-12d3-a456-426614174001"}
            )
            missing = await session.call_tool(
                tool, {**arguments, "run_id": "123e4567-e89b-12d3-a456-426614174002"}
            )
            assert wrong.is_error and hidden.is_error and missing.is_error
            assert wrong.model_dump() == hidden.model_dump() == missing.model_dump()
            rendered = str(hidden.model_dump())
            for value in (
                "RESTRICTED",
                "approval_owner",
                "approval_decision",
                "123e4567-e89b-12d3-a456-426614174001",
            ):
                assert value not in rendered
            allowed = await session.call_tool(tool, arguments)
            assert not allowed.is_error
            replay = await session.call_tool(tool, arguments)
            assert replay.is_error
            assert replay.model_dump() == wrong.model_dump()

    asyncio.run(verify())

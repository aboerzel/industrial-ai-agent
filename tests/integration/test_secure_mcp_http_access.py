import asyncio
import os
import socket
import subprocess
import sys
import time
from collections.abc import Iterator

import pytest
from mcp.shared.exceptions import MCPError

from industrial_ai_agent.infrastructure.factory_mcp_client import (
    StreamableHttpServerParameters,
    open_mcp_session,
)

_INDUSTRIAL_TOKEN = "industrial-http-test-token"
_CODEX_TOKEN = "codex-http-test-token"
_SERVER_SOURCE = """
import os
from mcp.server.mcpserver import MCPServer
from industrial_ai_agent.application.mcp_access import McpPermission
from industrial_ai_agent.infrastructure.factory_mcp_server import create_factory_mcp_server
from industrial_ai_agent.infrastructure.in_memory_machine_status_repository import InMemoryMachineStatusRepository
from industrial_ai_agent.infrastructure.in_memory_maintenance_ticket_repository import InMemoryMaintenanceTicketRepository
from industrial_ai_agent.infrastructure.in_memory_product_history_repository import InMemoryProductHistoryRepository
from industrial_ai_agent.infrastructure.mcp_access_control import create_demo_mcp_access_control
from industrial_ai_agent.tools.machine_status import MachineStatusCapability
from industrial_ai_agent.tools.maintenance_ticket import MaintenanceTicketCapability
from industrial_ai_agent.tools.product_history import ProductHistoryCapability

server: MCPServer
async def tools():
    return await server.list_tools()

access = create_demo_mcp_access_control(
    tools=tools,
    required_permission=lambda name: {
        'get_product_history': McpPermission.READ_FACTORY,
        'get_machine_status': McpPermission.READ_FACTORY,
        'create_maintenance_ticket': McpPermission.CREATE_MAINTENANCE_TICKET,
    }[name],
)
product = ProductHistoryCapability(InMemoryProductHistoryRepository())
machine = MachineStatusCapability(InMemoryMachineStatusRepository())
ticket = MaintenanceTicketCapability(InMemoryMaintenanceTicketRepository())
server = create_factory_mcp_server(
    product_history=product,
    machine_status=machine,
    maintenance_ticket=ticket,
    access_control=access,
    capabilities_for_context=lambda context: (product, machine, ticket),
)
server.run(transport='streamable-http', host='127.0.0.1', port=int(os.environ['TEST_MCP_PORT']), streamable_http_path='/mcp')
"""


@pytest.fixture(scope="module")
def secure_factory_server() -> Iterator[str]:
    port = _free_port()
    environment = {
        **os.environ,
        "TEST_MCP_PORT": str(port),
        "MCP_INDUSTRIAL_AGENT_TOKEN": _INDUSTRIAL_TOKEN,
        "MCP_CODEX_DEVELOPMENT_TOKEN": _CODEX_TOKEN,
    }
    process = subprocess.Popen(
        [sys.executable, "-c", _SERVER_SOURCE],
        env=environment,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        _wait_for_listening_port(process, port)
        yield f"http://127.0.0.1:{port}/mcp"
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


def test_industrial_client_discovers_write_tool(secure_factory_server: str) -> None:
    names = asyncio.run(_tool_names(secure_factory_server, _INDUSTRIAL_TOKEN))

    assert names == {
        "get_product_history",
        "get_machine_status",
        "create_maintenance_ticket",
    }


def test_codex_client_discovers_only_read_tools_and_cannot_call_write_tool(
    secure_factory_server: str,
) -> None:
    async def verify() -> tuple[set[str], str]:
        async with open_mcp_session(
            StreamableHttpServerParameters(
                url=secure_factory_server,
                bearer_token=_CODEX_TOKEN,
                request_headers={
                    "X-Client": "industrial-agent",
                    "X-Clearance": "CONFIDENTIAL",
                    "X-Permissions": "CREATE_MAINTENANCE_TICKET",
                    "traceparent": "00-4bf92f3577b34da6a3ce929d0e0e4736-"
                    "00f067aa0ba902b7-01",
                    "tracestate": "vendor=untrusted",
                },
            )
        ) as session:
            await session.initialize()
            listed = await session.list_tools()
            with pytest.raises(MCPError, match="MCP tool is not authorized"):
                await session.call_tool(
                    "create_maintenance_ticket",
                    {
                        "station_id": "S04",
                        "summary": "must be rejected",
                        "request_id": "codex-direct-write",
                    },
                )
        return {tool.name for tool in listed.tools}, "denied"

    names, outcome = asyncio.run(verify())

    assert names == {"get_product_history", "get_machine_status"}
    assert outcome == "denied"


def test_missing_and_malformed_authorization_are_denied(
    secure_factory_server: str,
) -> None:
    async def initialize(token: str | None) -> None:
        async with open_mcp_session(
            StreamableHttpServerParameters(
                url=secure_factory_server,
                bearer_token=token,
            )
        ) as session:
            await session.initialize()

    with pytest.raises(BaseExceptionGroup) as missing_error:
        asyncio.run(initialize(None))
    assert _contains_mcp_error(missing_error.value, "MCP authentication failed")

    with pytest.raises(BaseExceptionGroup) as malformed_error:
        asyncio.run(initialize("not-a-valid-token"))
    assert _contains_mcp_error(malformed_error.value, "MCP authentication failed")


async def _tool_names(url: str, token: str) -> set[str]:
    async with open_mcp_session(
        StreamableHttpServerParameters(url=url, bearer_token=token)
    ) as session:
        await session.initialize()
        listed = await session.list_tools()
    return {tool.name for tool in listed.tools}


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        return listener.getsockname()[1]


def _wait_for_listening_port(process: subprocess.Popen[str], port: int) -> None:
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        if process.poll() is not None:
            stderr = process.stderr.read() if process.stderr is not None else ""
            raise RuntimeError(
                f"Secure MCP test server exited during startup: {stderr}"
            )
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as client:
            if client.connect_ex(("127.0.0.1", port)) == 0:
                return
        time.sleep(0.05)
    raise RuntimeError("Secure MCP test server did not start within 5 seconds")


def _contains_mcp_error(error: BaseException, message: str) -> bool:
    if isinstance(error, MCPError):
        return error.message == message
    if isinstance(error, BaseExceptionGroup):
        return any(_contains_mcp_error(child, message) for child in error.exceptions)
    return False

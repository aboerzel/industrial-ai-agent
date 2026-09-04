import asyncio
import inspect
import sys

from mcp.client.stdio import StdioServerParameters
from mcp.types import CallToolResult

from industrial_ai_agent.infrastructure.factory_mcp_client import (
    FactoryMcpSmokeResult,
    StreamableHttpServerParameters,
    run_factory_mcp_smoke,
)
from industrial_ai_agent.infrastructure.factory_mcp_server import (
    FACTORY_MCP_SERVER_NAME,
    FACTORY_MCP_SERVER_VERSION,
    create_default_factory_mcp_server,
    create_factory_mcp_server,
)
from industrial_ai_agent.tools.machine_status import MachineStatusResult
from industrial_ai_agent.tools.product_history import ProductHistoryResult


def test_factory_mcp_server_advertises_the_two_expected_tool_schemas() -> None:
    tools = asyncio.run(create_default_factory_mcp_server().list_tools())

    tools_by_name = {tool.name: tool for tool in tools}
    assert set(tools_by_name) == {"get_product_history", "get_machine_status"}
    assert tools_by_name["get_product_history"].input_schema["required"] == [
        "product_id"
    ]
    assert tools_by_name["get_machine_status"].input_schema["required"] == [
        "station_id"
    ]


def test_factory_mcp_tool_handlers_delegate_to_injected_capabilities() -> None:
    product_history = _RecordingProductHistoryCapability()
    machine_status = _RecordingMachineStatusCapability()
    server = create_factory_mcp_server(
        product_history=product_history,  # type: ignore[arg-type]
        machine_status=machine_status,  # type: ignore[arg-type]
    )

    async def call_tools() -> tuple[dict[str, object], dict[str, object]]:
        product_call = await server.call_tool(
            "get_product_history", {"product_id": "P4711"}
        )
        machine_call = await server.call_tool(
            "get_machine_status", {"station_id": "S04"}
        )
        assert isinstance(product_call, CallToolResult)
        assert isinstance(machine_call, CallToolResult)
        return product_call.structured_content, machine_call.structured_content

    product_content, machine_content = asyncio.run(call_tools())

    assert product_history.product_ids == ["P4711"]
    assert machine_status.station_ids == ["S04"]
    assert product_content == {
        "product_id": "P4711",
        "found": False,
        "steps": [],
        "classification": 2,
    }
    assert machine_content == {
        "station_id": "S04",
        "found": False,
        "state": None,
        "active_error_code": None,
        "classification": 2,
    }


def test_factory_mcp_preserves_structured_not_found_results() -> None:
    server = create_default_factory_mcp_server()

    async def call_unknowns() -> tuple[dict[str, object], dict[str, object]]:
        product_call = await server.call_tool(
            "get_product_history", {"product_id": "P9999"}
        )
        machine_call = await server.call_tool(
            "get_machine_status", {"station_id": "S99"}
        )
        assert isinstance(product_call, CallToolResult)
        assert isinstance(machine_call, CallToolResult)
        return product_call.structured_content, machine_call.structured_content

    product_content, machine_content = asyncio.run(call_unknowns())

    assert product_content == {
        "product_id": "P9999",
        "found": False,
        "steps": [],
        "classification": 2,
    }
    assert machine_content == {
        "station_id": "S99",
        "found": False,
        "state": None,
        "active_error_code": None,
        "classification": 2,
    }


def test_official_mcp_stdio_client_discovers_and_calls_factory_tools() -> None:
    result = asyncio.run(
        run_factory_mcp_smoke(
            StdioServerParameters(
                command=sys.executable,
                args=["-m", "industrial_ai_agent.infrastructure.factory_mcp_server"],
            )
        )
    )

    _assert_factory_smoke_result(result)


def test_streamable_http_matches_stdio_factory_mcp_protocol_and_results(
    factory_mcp_http_transport: StreamableHttpServerParameters,
) -> None:
    stdio_result = asyncio.run(
        run_factory_mcp_smoke(
            StdioServerParameters(
                command=sys.executable,
                args=["-m", "industrial_ai_agent.infrastructure.factory_mcp_server"],
            )
        )
    )
    http_result = asyncio.run(run_factory_mcp_smoke(factory_mcp_http_transport))

    assert http_result.server_name == stdio_result.server_name
    assert http_result.server_version == stdio_result.server_version
    assert http_result.tool_names == stdio_result.tool_names
    assert http_result.tool_schemas == stdio_result.tool_schemas
    assert http_result.product_history == stdio_result.product_history
    assert http_result.machine_status == stdio_result.machine_status
    assert http_result.unknown_product_history == stdio_result.unknown_product_history
    assert http_result.unknown_machine_status == stdio_result.unknown_machine_status


def _assert_factory_smoke_result(result: FactoryMcpSmokeResult) -> None:
    assert result.server_name == FACTORY_MCP_SERVER_NAME
    assert result.server_version == FACTORY_MCP_SERVER_VERSION
    assert result.protocol_version
    assert result.tool_names == ("get_product_history", "get_machine_status")
    assert result.product_history is not None
    assert result.product_history["product_id"] == "P4711"
    assert result.product_history["found"] is True
    assert result.product_history["steps"][-1]["error_code"] == "E-STOP-17"
    assert result.machine_status == {
        "station_id": "S04",
        "found": True,
        "state": "FAULTED",
        "active_error_code": "E-STOP-17",
        "classification": 2,
    }
    assert result.unknown_product_history == {
        "product_id": "P9999",
        "found": False,
        "steps": [],
        "classification": 2,
    }
    assert result.unknown_machine_status == {
        "station_id": "S99",
        "found": False,
        "state": None,
        "active_error_code": None,
        "classification": 2,
    }


def test_capability_result_types_do_not_depend_on_mcp() -> None:
    assert "mcp" not in inspect.getsource(ProductHistoryResult).casefold()
    assert "mcp" not in inspect.getsource(MachineStatusResult).casefold()


class _RecordingProductHistoryCapability:
    def __init__(self) -> None:
        self.product_ids: list[str] = []

    def get_product_history(self, product_id: str) -> ProductHistoryResult:
        self.product_ids.append(product_id)
        return ProductHistoryResult(product_id=product_id, found=False, steps=())


class _RecordingMachineStatusCapability:
    def __init__(self) -> None:
        self.station_ids: list[str] = []

    def get_machine_status(self, station_id: str) -> MachineStatusResult:
        self.station_ids.append(station_id)
        return MachineStatusResult(station_id=station_id, found=False)

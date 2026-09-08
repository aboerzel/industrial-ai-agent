import asyncio
import inspect
import os
import sys

import pytest
from mcp.client.stdio import StdioServerParameters
from mcp.server.mcpserver.exceptions import ToolError
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
from industrial_ai_agent.infrastructure.in_memory_factory_discovery_repository import (
    InMemoryFactoryDiscoveryRepository,
)
from industrial_ai_agent.tools.factory_discovery import FactoryDiscoveryCapability
from industrial_ai_agent.tools.machine_status import MachineStatusResult
from industrial_ai_agent.tools.product_history import ProductHistoryResult


def test_factory_mcp_server_advertises_read_and_maintenance_tool_schemas() -> None:
    tools = asyncio.run(create_default_factory_mcp_server().list_tools())

    tools_by_name = {tool.name: tool for tool in tools}
    assert set(tools_by_name) == {
        "list_stations",
        "get_station_overview",
        "list_products",
        "get_product_overview",
        "get_product_history",
        "get_machine_status",
        "get_maintenance_ticket",
        "create_maintenance_ticket",
    }
    assert tools_by_name["get_product_history"].input_schema["required"] == [
        "product_id"
    ]
    assert tools_by_name["get_machine_status"].input_schema["required"] == [
        "station_id"
    ]
    assert tools_by_name["get_maintenance_ticket"].input_schema["required"] == [
        "ticket_id"
    ]
    assert "required" not in tools_by_name["list_stations"].input_schema
    assert "required" not in tools_by_name["list_products"].input_schema
    assert tools_by_name["get_station_overview"].input_schema["required"] == [
        "station_id"
    ]
    assert tools_by_name["get_product_overview"].input_schema["required"] == [
        "product_id"
    ]
    assert tools_by_name["create_maintenance_ticket"].input_schema["required"] == [
        "station_id",
        "summary",
        "request_id",
    ]
    for tool in tools_by_name.values():
        assert tool.input_schema["additionalProperties"] is False


def test_factory_mcp_tool_handlers_delegate_to_injected_capabilities() -> None:
    product_history = _RecordingProductHistoryCapability()
    machine_status = _RecordingMachineStatusCapability()
    discovery = _RecordingFactoryDiscoveryCapability()
    server = create_factory_mcp_server(
        product_history=product_history,  # type: ignore[arg-type]
        machine_status=machine_status,  # type: ignore[arg-type]
        factory_discovery=discovery,  # type: ignore[arg-type]
    )

    async def call_tools() -> tuple[
        dict[str, object], dict[str, object], dict[str, object]
    ]:
        product_call = await server.call_tool(
            "get_product_history", {"product_id": "P4711"}
        )
        machine_call = await server.call_tool(
            "get_machine_status", {"station_id": "S04"}
        )
        stations_call = await server.call_tool("list_stations", {})
        assert isinstance(product_call, CallToolResult)
        assert isinstance(machine_call, CallToolResult)
        assert isinstance(stations_call, CallToolResult)
        return (
            product_call.structured_content,
            machine_call.structured_content,
            stations_call.structured_content,
        )

    product_content, machine_content, stations_content = asyncio.run(call_tools())

    assert product_history.product_ids == ["P4711"]
    assert machine_status.station_ids == ["S04"]
    assert discovery.list_station_calls == 1
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
    assert stations_content == {"stations": [], "classification": 0}


def test_factory_mcp_rejects_invalid_maintenance_ticket_inputs_before_dispatch() -> (
    None
):
    server = create_default_factory_mcp_server()

    async def call_invalid_tools() -> None:
        invalid_arguments = (
            {"station_id": "S04", "summary": "x"},
            {"station_id": 4, "summary": "x", "request_id": "schema-type"},
        )
        for arguments in invalid_arguments:
            with pytest.raises(ToolError, match="Error executing tool"):
                await server.call_tool("create_maintenance_ticket", arguments)

    asyncio.run(call_invalid_tools())


def test_factory_mcp_rejects_invalid_maintenance_ticket_id_before_dispatch() -> None:
    server = create_default_factory_mcp_server()

    async def call_invalid_tool() -> None:
        with pytest.raises(ToolError, match="Error executing tool"):
            await server.call_tool("get_maintenance_ticket", {"ticket_id": "MT-0001"})

    asyncio.run(call_invalid_tool())


def test_factory_mcp_reads_the_ticket_created_by_the_same_capability() -> None:
    server = create_default_factory_mcp_server()

    async def create_then_read() -> tuple[dict[str, object], dict[str, object]]:
        created = await server.call_tool(
            "create_maintenance_ticket",
            {
                "station_id": "S04",
                "summary": "Inspect QUALITY-09",
                "request_id": "ticket-read-test",
            },
        )
        assert isinstance(created, CallToolResult)
        ticket_id = created.structured_content["ticket_id"]
        assert isinstance(ticket_id, str)
        read = await server.call_tool(
            "get_maintenance_ticket", {"ticket_id": ticket_id}
        )
        assert isinstance(read, CallToolResult)
        return created.structured_content, read.structured_content

    created, read = asyncio.run(create_then_read())

    assert read == {
        "ticket_id": created["ticket_id"],
        "found": True,
        "status": "OPEN",
        "station_id": "S04",
        "summary": "Inspect QUALITY-09",
        "classification": 2,
    }


def test_factory_mcp_returns_a_bounded_not_found_ticket_result() -> None:
    server = create_default_factory_mcp_server()

    async def call_unknown() -> dict[str, object]:
        result = await server.call_tool(
            "get_maintenance_ticket", {"ticket_id": "MT-FFFFFFFFFFFF"}
        )
        assert isinstance(result, CallToolResult)
        return result.structured_content

    assert asyncio.run(call_unknown()) == {
        "ticket_id": "MT-FFFFFFFFFFFF",
        "found": False,
        "status": None,
        "station_id": None,
        "summary": None,
        "classification": 2,
    }


def test_factory_mcp_rejects_unknown_arguments_before_capability_dispatch() -> None:
    product_history = _RecordingProductHistoryCapability()
    machine_status = _RecordingMachineStatusCapability()
    server = create_factory_mcp_server(
        product_history=product_history,  # type: ignore[arg-type]
        machine_status=machine_status,  # type: ignore[arg-type]
        factory_discovery=FactoryDiscoveryCapability(
            InMemoryFactoryDiscoveryRepository()
        ),
    )

    async def call_invalid_tool() -> None:
        with pytest.raises(ToolError, match="Error executing tool"):
            await server.call_tool(
                "get_product_history",
                {"product_id": "P4711", "unexpected": "reject"},
            )

    asyncio.run(call_invalid_tool())

    assert product_history.product_ids == []
    assert machine_status.station_ids == []


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
    result = asyncio.run(run_factory_mcp_smoke(_factory_mcp_stdio_transport()))

    _assert_factory_smoke_result(result)


def test_streamable_http_matches_stdio_factory_mcp_protocol_and_results(
    factory_mcp_http_transport: StreamableHttpServerParameters,
) -> None:
    # The HTTP fixture deliberately uses the default in-memory demo server.
    # Keep both transports on that same data source when a local PostgreSQL URL is set.
    stdio_result = asyncio.run(
        run_factory_mcp_smoke(_factory_mcp_stdio_transport(database_url=""))
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


def _factory_mcp_stdio_transport(
    database_url: str | None = None,
) -> StdioServerParameters:
    if database_url is None:
        database_url = os.getenv("FACTORY_DATABASE_URL")
    return StdioServerParameters(
        command=sys.executable,
        args=["-m", "industrial_ai_agent.infrastructure.factory_mcp_server"],
        env={"FACTORY_DATABASE_URL": database_url} if database_url else None,
    )


def _assert_factory_smoke_result(result: FactoryMcpSmokeResult) -> None:
    assert result.server_name == FACTORY_MCP_SERVER_NAME
    assert result.server_version == FACTORY_MCP_SERVER_VERSION
    assert result.protocol_version
    assert result.tool_names == (
        "list_stations",
        "get_station_overview",
        "list_products",
        "get_product_overview",
        "get_product_history",
        "get_machine_status",
        "get_maintenance_ticket",
        "create_maintenance_ticket",
    )
    assert result.product_history is not None
    assert result.product_history["product_id"] == "P4711"
    assert result.product_history["found"] is True
    expected_error_code = (
        "QUALITY-09" if os.getenv("FACTORY_DATABASE_URL") else "E-STOP-17"
    )
    assert result.product_history["steps"][-1]["error_code"] == expected_error_code
    assert result.machine_status == {
        "station_id": "S04",
        "found": True,
        "state": "FAULTED",
        "active_error_code": expected_error_code,
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


class _RecordingFactoryDiscoveryCapability:
    def __init__(self) -> None:
        self.list_station_calls = 0

    def list_stations(self):
        from industrial_ai_agent.tools.factory_discovery import StationListResult

        self.list_station_calls += 1
        return StationListResult(stations=(), classification=0)

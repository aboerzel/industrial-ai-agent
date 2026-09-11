import asyncio
import inspect
from pathlib import Path

import pytest
from mcp.server.mcpserver.exceptions import ToolError

from industrial_ai_agent.application.hardware_recovery import (
    HardwareRecoveryExecutionService,
    HardwareRecoveryPreparationService,
)
from industrial_ai_agent.application.mcp_access import McpPermission
from industrial_ai_agent.domain.machine_status import MachineState
from industrial_ai_agent.domain.security import DataClassification, SecurityContext
from industrial_ai_agent.infrastructure.hardware_mcp_server import (
    _HARDWARE_TOOL_PERMISSIONS,
    HARDWARE_MCP_SERVER_NAME,
    create_hardware_mcp_server,
)
from industrial_ai_agent.infrastructure.mcp_access_control import (
    DemoBearerTokenAuthenticator,
    McpAuthorizationError,
    McpHttpAccessControl,
    RegisteredMcpClientContextResolver,
    _registration,
)
from industrial_ai_agent.infrastructure.simulated_position_encoder_adapter import (
    SimulatedPositionEncoderAdapter,
)


class _RecordingPositionEncoderAdapter(SimulatedPositionEncoderAdapter):
    def __init__(self, *, station_mode: MachineState = MachineState.STOPPED) -> None:
        super().__init__(station_mode=station_mode)
        self.execute_calls = 0

    def execute_operation(self, operation):  # type: ignore[no-untyped-def]
        self.execute_calls += 1
        return super().execute_operation(operation)


def test_hardware_mcp_exposes_only_strict_bounded_hardware_recovery_tools() -> None:
    server, _ = _server()
    tools = asyncio.run(server.list_tools())

    assert HARDWARE_MCP_SERVER_NAME == "hardware_mcp"
    assert [tool.name for tool in tools] == [
        "get_position_reference_status",
        "prepare_reference_calibration",
        "execute_reference_calibration",
    ]
    assert tools[0].annotations.read_only_hint is True
    assert tools[1].annotations.read_only_hint is True
    assert tools[2].annotations.read_only_hint is False
    for tool in tools[:2]:
        assert tool.input_schema["additionalProperties"] is False
        assert set(tool.input_schema["properties"]) == {"station_id", "device_id"}
    assert tools[2].input_schema["additionalProperties"] is False
    assert set(tools[2].input_schema["properties"]) == {
        "station_id",
        "device_id",
        "run_id",
        "action_id",
    }


def test_status_returns_bounded_s04_state_without_mutation() -> None:
    server, adapter = _server()
    before = adapter.read_state(adapter.device_id)
    result = _call(server, "get_position_reference_status")

    assert result == {
        "station_id": "S04",
        "device_id": "POSITION-ENC-02",
        "connection_state": "CONNECTED",
        "operational_state": "FAULT",
        "reference_valid": False,
        "position_deviation_mm": 0.43,
        "configured_tolerance_mm": 0.2,
        "station_mode": "STOPPED",
        "axis_motion_state": "IDLE",
        "product_present": False,
        "calibration_supported": True,
        "classification": "CONFIDENTIAL",
    }
    assert adapter.read_state(adapter.device_id) == before
    assert adapter.execute_calls == 0


def test_preparation_returns_trusted_controlled_proposal_without_execution() -> None:
    server, adapter = _server()
    result = _call(server, "prepare_reference_calibration")

    assert result["station_id"] == "S04"
    assert result["device_id"] == "POSITION-ENC-02"
    assert result["proposed_operation"] == "reference_calibration"
    assert result["action_risk_class"] == "CONTROLLED_ACTION"
    assert result["requires_approval"] is True
    assert result["classification"] == "CONFIDENTIAL"
    assert [item["condition_type"] for item in result["preconditions"]] == [
        "station_stopped",
        "axis_idle",
        "no_product_present",
        "device_connected",
    ]
    assert {item["status"] for item in result["precondition_evaluations"]} == {"PASSED"}
    assert result["verification_plan"] == [
        {"criterion_type": "reference_valid", "maximum_abs_deviation": None},
        {
            "criterion_type": "position_deviation_within_tolerance",
            "maximum_abs_deviation": 0.2,
        },
    ]
    assert adapter.execute_calls == 0


def test_preparation_reports_failed_precondition_without_execution() -> None:
    server, adapter = _server(station_mode=MachineState.RUNNING)
    result = _call(server, "prepare_reference_calibration")

    station_precondition = next(
        item
        for item in result["precondition_evaluations"]
        if item["condition_type"] == "station_stopped"
    )
    assert station_precondition == {
        "condition_type": "station_stopped",
        "status": "FAILED",
        "observed_value": "RUNNING",
    }
    assert adapter.execute_calls == 0


def test_execute_is_unavailable_without_a_trusted_execution_service() -> None:
    server, adapter = _server()

    error = _tool_error(
        server,
        "execute_reference_calibration",
        "S04",
        "POSITION-ENC-02",
        run_id="11111111-1111-1111-1111-111111111111",
        action_id="controlled-action-1",
    )

    assert "POSITION-ENC-02" not in str(error)
    assert adapter.execute_calls == 0


def test_mcp_execute_delegates_to_the_closed_loop_execution_service() -> None:
    source = inspect.getsource(create_hardware_mcp_server)

    assert "recovery_execution.execute_reference_calibration" in source
    assert "execute_operation(" not in source
    assert "HardwareRecoveryExecutionService" in inspect.getsource(
        HardwareRecoveryExecutionService
    )


@pytest.mark.parametrize(
    ("tool_name", "extra_argument"),
    (
        ("prepare_reference_calibration", {"risk_class": "READ_ONLY"}),
        ("prepare_reference_calibration", {"requires_approval": False}),
        ("prepare_reference_calibration", {"tolerance": 99}),
        ("prepare_reference_calibration", {"approved": True}),
        ("get_position_reference_status", {"backend": "other"}),
    ),
)
def test_tool_inputs_reject_model_supplied_safety_and_backend_values(
    tool_name: str, extra_argument: dict[str, object]
) -> None:
    server, adapter = _server()

    async def call() -> None:
        with pytest.raises(ToolError):
            await server.call_tool(
                tool_name,
                {"station_id": "S04", "device_id": "POSITION-ENC-02", **extra_argument},
            )

    asyncio.run(call())
    assert adapter.execute_calls == 0


def test_permissions_are_distinct_for_status_preparation_and_execution() -> None:
    status_context = _registration(
        token="status-token",
        client_id="status-reader",
        clearance=DataClassification.CONFIDENTIAL,
        permissions=frozenset({McpPermission.READ_HARDWARE_STATUS}),
    )
    preparation_context = _registration(
        token="preparation-token",
        client_id="preparation-reader",
        clearance=DataClassification.CONFIDENTIAL,
        permissions=frozenset({McpPermission.PREPARE_HARDWARE_RECOVERY}),
    )
    execution_context = _registration(
        token="execution-token",
        client_id="recovery-executor",
        clearance=DataClassification.CONFIDENTIAL,
        permissions=frozenset({McpPermission.EXECUTE_HARDWARE_RECOVERY}),
    )
    server, _ = _server()
    access = McpHttpAccessControl(
        authenticator=DemoBearerTokenAuthenticator(
            (status_context, preparation_context, execution_context)
        ),
        resolver=RegisteredMcpClientContextResolver(
            (status_context, preparation_context, execution_context)
        ),
        tools=server.list_tools,
        required_permission=lambda name: _HARDWARE_TOOL_PERMISSIONS[name],
    )
    status = access.access_context_from_headers(
        {"authorization": "Bearer status-token"}
    )
    preparation = access.access_context_from_headers(
        {"authorization": "Bearer preparation-token"}
    )
    execution = access.access_context_from_headers(
        {"authorization": "Bearer execution-token"}
    )

    access.authorize_tool(status, "get_position_reference_status")
    access.authorize_tool(preparation, "prepare_reference_calibration")
    access.authorize_tool(execution, "execute_reference_calibration")
    with pytest.raises(McpAuthorizationError, match="MCP tool is not authorized"):
        access.authorize_tool(status, "prepare_reference_calibration")
    with pytest.raises(McpAuthorizationError, match="MCP tool is not authorized"):
        access.authorize_tool(preparation, "get_position_reference_status")
    with pytest.raises(McpAuthorizationError, match="MCP tool is not authorized"):
        access.authorize_tool(preparation, "execute_reference_calibration")
    with pytest.raises(McpAuthorizationError, match="MCP tool is not authorized"):
        access.authorize_tool(status, "execute_reference_calibration")
    assert [tool.name for tool in asyncio.run(access.visible_tools(status))] == [
        "get_position_reference_status"
    ]
    assert [tool.name for tool in asyncio.run(access.visible_tools(preparation))] == [
        "prepare_reference_calibration"
    ]
    assert [tool.name for tool in asyncio.run(access.visible_tools(execution))] == [
        "execute_reference_calibration"
    ]
    assert set(_HARDWARE_TOOL_PERMISSIONS) == {
        "get_position_reference_status",
        "prepare_reference_calibration",
        "execute_reference_calibration",
    }


def test_insufficient_clearance_and_unknown_target_have_the_same_neutral_error() -> (
    None
):
    restricted_context = SecurityContext(
        subject_id="internal-reader",
        roles=("internal-reader",),
        clearance=DataClassification.INTERNAL,
        authenticated=True,
    )
    restricted_server, restricted_adapter = _server(
        default_security_context=restricted_context
    )
    server, _ = _server()

    restricted_error = _tool_error(
        restricted_server, "get_position_reference_status", "S04", "POSITION-ENC-02"
    )
    unknown_error = _tool_error(
        server, "get_position_reference_status", "S04", "POSITION-ENC-99"
    )

    assert str(restricted_error) == str(unknown_error)
    assert "POSITION-ENC-02" not in str(restricted_error)
    assert restricted_adapter.execute_calls == 0


def test_core_layers_do_not_import_the_hardware_mcp_transport() -> None:
    project_root = Path(__file__).resolve().parents[2]
    for path in (
        project_root / "src/industrial_ai_agent/domain/physical_device.py",
        project_root / "src/industrial_ai_agent/domain/physical_device_port.py",
        project_root / "src/industrial_ai_agent/application/closed_loop_recovery.py",
        project_root / "src/industrial_ai_agent/application/hardware_recovery.py",
    ):
        assert "hardware_mcp_server" not in path.read_text(encoding="utf-8")
        assert "from mcp" not in path.read_text(encoding="utf-8")


def _server(
    *,
    station_mode: MachineState = MachineState.STOPPED,
    default_security_context: SecurityContext | None = None,
):
    adapter = _RecordingPositionEncoderAdapter(station_mode=station_mode)
    service = HardwareRecoveryPreparationService(physical_devices=adapter)
    server = create_hardware_mcp_server(
        recovery_preparation=service,
        **(
            {"default_security_context": default_security_context}
            if default_security_context is not None
            else {}
        ),
    )
    return server, adapter


def _call(server, tool_name: str) -> dict[str, object]:  # type: ignore[no-untyped-def]
    async def call() -> dict[str, object]:
        result = await server.call_tool(
            tool_name,
            {"station_id": "S04", "device_id": "POSITION-ENC-02"},
        )
        return result.structured_content

    return asyncio.run(call())


def _tool_error(  # type: ignore[no-untyped-def]
    server,
    tool_name: str,
    station_id: str,
    device_id: str,
    **extra_arguments: object,
) -> ToolError:
    async def call() -> ToolError:
        with pytest.raises(ToolError) as error:
            await server.call_tool(
                tool_name,
                {
                    "station_id": station_id,
                    "device_id": device_id,
                    **extra_arguments,
                },
            )
        return error.value

    return asyncio.run(call())

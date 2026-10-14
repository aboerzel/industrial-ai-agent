"""Direct MCP calls and HITL resumes share authoritative execution claims."""

import asyncio
import json
from contextlib import asynccontextmanager
from dataclasses import replace
from types import SimpleNamespace
from uuid import UUID

import pytest
from langchain_core.tools import StructuredTool
from langgraph.checkpoint.memory import InMemorySaver
from test_langgraph_mcp_hitl import (
    FakeLLMClient,
    _action_response,
    _agent,
    _final_response,
)

from industrial_ai_agent.agent.mcp_tool_provider import McpToolSession
from industrial_ai_agent.agent.run_classification_policy import AgentRunProfile
from industrial_ai_agent.agent.tool_policy import ToolOperation, ToolPolicy
from industrial_ai_agent.application.hardware_recovery import (
    HardwareRecoveryExecutionService,
    HardwareRecoveryPreparationService,
)
from industrial_ai_agent.application.mcp_access import McpPermission
from industrial_ai_agent.domain.security import DataClassification
from industrial_ai_agent.infrastructure.action_approval import (
    AgentRunStoreActionApprovalPort,
)
from industrial_ai_agent.infrastructure.api.run_store import InMemoryAgentRunStore
from industrial_ai_agent.infrastructure.factory_mcp_server import (
    create_factory_mcp_server,
)
from industrial_ai_agent.infrastructure.hardware_mcp_server import (
    create_hardware_mcp_server,
)
from industrial_ai_agent.infrastructure.in_memory_factory_discovery_repository import (
    InMemoryFactoryDiscoveryRepository,
)
from industrial_ai_agent.infrastructure.in_memory_machine_status_repository import (
    InMemoryMachineStatusRepository,
)
from industrial_ai_agent.infrastructure.in_memory_maintenance_ticket_repository import (
    InMemoryMaintenanceTicketRepository,
)
from industrial_ai_agent.infrastructure.in_memory_product_history_repository import (
    InMemoryProductHistoryRepository,
)
from industrial_ai_agent.infrastructure.mcp_access_control import (
    DemoBearerTokenAuthenticator,
    McpHttpAccessControl,
    RegisteredMcpClientContextResolver,
    _registration,
)
from industrial_ai_agent.infrastructure.simulated_position_encoder_adapter import (
    SimulatedPositionEncoderAdapter,
)
from industrial_ai_agent.tools.factory_discovery import FactoryDiscoveryCapability
from industrial_ai_agent.tools.machine_status import MachineStatusCapability
from industrial_ai_agent.tools.maintenance_ticket import MaintenanceTicketCapability
from industrial_ai_agent.tools.product_history import ProductHistoryCapability
from industrial_ai_agent.tools.tool_contracts import (
    CreateMaintenanceTicketExecutionArguments,
)

RUN_ID = UUID("123e4567-e89b-12d3-a456-426614174000")
ACTION_ID = "ticket-call-1"
SUMMARY = "Investigate QUALITY-09"


class RecordingDevice(SimulatedPositionEncoderAdapter):
    def __init__(self):
        super().__init__()
        self.execute_calls = 0

    def execute_operation(self, operation):
        self.execute_calls += 1
        return super().execute_operation(operation)


def _setup(
    kind="factory", clearance=DataClassification.CONFIDENTIAL, action_permission=True
):
    store = InMemoryAgentRunStore()
    asyncio.run(
        store.create(RUN_ID, data_classification=DataClassification.CONFIDENTIAL)
    )
    seen_contexts = []

    def store_for_context(context):
        seen_contexts.append(context)
        return store

    claims = AgentRunStoreActionApprovalPort(store_for_context)
    repo = InMemoryMaintenanceTicketRepository()
    device = RecordingDevice()
    permissions = {
        McpPermission.READ_FACTORY,
        McpPermission.READ_HARDWARE_STATUS,
        McpPermission.PREPARE_HARDWARE_RECOVERY,
    }
    if action_permission:
        permissions.update(
            {
                McpPermission.CREATE_MAINTENANCE_TICKET,
                McpPermission.EXECUTE_HARDWARE_RECOVERY,
            }
        )
    registration = _registration(
        token="action-test-token",
        client_id="action-test",
        clearance=clearance,
        permissions=frozenset(permissions),
    )

    async def tools():
        return await server.list_tools()

    access = McpHttpAccessControl(
        authenticator=DemoBearerTokenAuthenticator((registration,)),
        resolver=RegisteredMcpClientContextResolver((registration,)),
        tools=tools,
        required_permission=lambda name: {
            "create_maintenance_ticket": McpPermission.CREATE_MAINTENANCE_TICKET,
            "execute_reference_calibration": McpPermission.EXECUTE_HARDWARE_RECOVERY,
            "prepare_reference_calibration": McpPermission.PREPARE_HARDWARE_RECOVERY,
            "get_position_reference_status": McpPermission.READ_HARDWARE_STATUS,
        }.get(name, McpPermission.READ_FACTORY),
    )
    if kind == "factory":
        server = create_factory_mcp_server(
            product_history=ProductHistoryCapability(
                InMemoryProductHistoryRepository()
            ),
            machine_status=MachineStatusCapability(InMemoryMachineStatusRepository()),
            factory_discovery=FactoryDiscoveryCapability(
                InMemoryFactoryDiscoveryRepository()
            ),
            maintenance_ticket=MaintenanceTicketCapability(
                repo, approval_claims=claims
            ),
            access_control=access,
        )
    else:
        preparation = HardwareRecoveryPreparationService(physical_devices=device)
        server = create_hardware_mcp_server(
            recovery_preparation=preparation,
            position_reference_devices=device,
            recovery_execution=HardwareRecoveryExecutionService(
                preparation=preparation, physical_devices=device, approval_claims=claims
            ),
            access_control=access,
        )
    context = SimpleNamespace(headers={"authorization": "Bearer action-test-token"})
    return server, store, repo, device, context, seen_contexts


def _payload(kind):
    return {
        "action": "create_maintenance_ticket"
        if kind == "factory"
        else "execute_reference_calibration",
        "action_id": ACTION_ID,
        "arguments": {"station_id": "S04", "summary": SUMMARY}
        if kind == "factory"
        else {
            "station_id": "S04",
            "device_id": "POSITION-ENC-02",
            "operation_type": "reference_calibration",
        },
    }


async def _approve(store, kind, *, decision="approve", approval_execution_id=None):
    pending = await store.wait_for_approval(
        RUN_ID, _payload(kind), approval_execution_id=approval_execution_id
    )
    await store.claim_resume(
        RUN_ID, decision=decision, approval_clearance=DataClassification.CONFIDENTIAL
    )
    return pending.approval_request["approval_execution_id"]


def _arguments(kind, execution_id=ACTION_ID):
    return (
        {
            "run_id": str(RUN_ID),
            "station_id": "S04",
            "summary": SUMMARY,
            "request_id": execution_id,
        }
        if kind == "factory"
        else {
            "run_id": str(RUN_ID),
            "station_id": "S04",
            "device_id": "POSITION-ENC-02",
            "action_id": execution_id,
        }
    )


async def _execute(server, kind, context, arguments=None):
    name = _payload(kind)["action"]
    return await server._tool_manager.get_tool(name).fn(
        **(arguments or _arguments(kind)), ctx=context
    )


@pytest.mark.parametrize("kind", ["factory", "hardware"])
@pytest.mark.parametrize(
    "case",
    [
        "public",
        "no_permission",
        "no_approval",
        "wrong_action",
        "wrong_target",
        "wrong_profile",
        "rejected",
        "low_approver",
        "hidden_run",
    ],
)
def test_direct_protected_mcp_denies_without_correct_authoritative_approval(kind, case):
    server, store, repo, device, context, _ = _setup(
        kind,
        clearance=DataClassification.PUBLIC
        if case == "public"
        else DataClassification.CONFIDENTIAL,
        action_permission=case != "no_permission",
    )

    async def verify():
        execution_id = ACTION_ID
        if case != "no_approval":
            execution_id = await _approve(
                store,
                "hardware"
                if kind == "factory" and case == "wrong_action"
                else "factory"
                if case == "wrong_action"
                else kind,
                decision="reject" if case == "rejected" else "approve",
            )
        if case in {"wrong_profile", "low_approver", "hidden_run"}:
            record = await store.get(RUN_ID)
            changes = {
                "wrong_profile": {"run_profile": AgentRunProfile.PUBLIC_INFORMATION},
                "low_approver": {
                    "approval_decided_clearance": DataClassification.PUBLIC
                },
                "hidden_run": {"data_classification": DataClassification.RESTRICTED},
            }[case]
            store._records[RUN_ID] = replace(record, **changes)
        arguments = _arguments(kind, execution_id)
        if case == "wrong_target":
            if kind == "factory":
                arguments["summary"] = "Unapproved different action"
            else:
                arguments["device_id"] = "POSITION-ENC-03"
        with pytest.raises((PermissionError, LookupError)) as denied:
            await _execute(server, kind, context, arguments)
        assert str(denied.value) in {
            "MCP tool is not authorized",
            "Protected action is not authorized",
            "Position-reference information is unavailable",
        }

    asyncio.run(verify())
    assert len(repo.tickets) == 0
    assert device.execute_calls == 0


@pytest.mark.parametrize("kind", ["factory", "hardware"])
def test_direct_valid_approval_executes_once_and_replay_cannot_execute_again(kind):
    server, store, repo, device, context, seen = _setup(kind)

    async def verify():
        execution_id = await _approve(store, kind)
        arguments = _arguments(kind, execution_id)
        first = await _execute(server, kind, context, arguments)
        if kind == "factory":
            assert await _execute(server, kind, context, arguments) == first
        else:
            with pytest.raises((PermissionError, LookupError)):
                await _execute(server, kind, context, arguments)

    asyncio.run(verify())
    assert len(repo.tickets) == (1 if kind == "factory" else 0)
    assert device.execute_calls == (1 if kind == "hardware" else 0)
    assert all(item.clearance is DataClassification.CONFIDENTIAL for item in seen)


def test_preparation_does_not_require_or_consume_execution_approval():
    server, store, _, device, context, _ = _setup("hardware")
    result = server._tool_manager.get_tool("prepare_reference_calibration").fn(
        station_id="S04", ctx=context
    )
    assert result["requires_approval"] is True
    assert device.execute_calls == 0
    assert asyncio.run(store.get(RUN_ID)).approval_request is None


@pytest.mark.parametrize("kind", ["factory", "hardware"])
def test_concurrent_approved_invocations_allow_only_one_execution(kind):
    server, store, repo, device, context, _ = _setup(kind)

    async def verify():
        execution_id = await _approve(store, kind)
        arguments = _arguments(kind, execution_id)
        results = await asyncio.gather(
            _execute(server, kind, context, arguments),
            _execute(server, kind, context, arguments),
            return_exceptions=True,
        )
        assert sum(
            isinstance(result, (PermissionError, LookupError)) for result in results
        ) == (0 if kind == "factory" else 1)
        if kind == "factory":
            assert results[0] == results[1]

    asyncio.run(verify())
    assert len(repo.tickets) + device.execute_calls == 1


def test_public_read_is_still_available():
    server, _, repo, _, context, _ = _setup(
        clearance=DataClassification.PUBLIC, action_permission=False
    )
    result = server._tool_manager.get_tool("list_stations").fn(ctx=context)
    assert result is not None
    assert repo.tickets == ()


def test_normal_hitl_and_direct_mcp_use_the_same_persisted_execution_guard():
    server, store, repo, _, context, _ = _setup()

    class Provider:
        @asynccontextmanager
        async def open_session(self):
            async def execute(
                station_id: str, summary: str, request_id: str, run_id: str
            ):
                result = await _execute(
                    server,
                    "factory",
                    context,
                    {
                        "station_id": station_id,
                        "summary": summary,
                        "request_id": request_id,
                        "run_id": run_id,
                    },
                )
                return json.dumps(result)

            yield McpToolSession(
                tools=(
                    StructuredTool.from_function(
                        coroutine=execute,
                        name="create_maintenance_ticket",
                        description="Create an approved maintenance ticket.",
                        args_schema=CreateMaintenanceTicketExecutionArguments,
                    ),
                ),
                discovered_tool_names=("create_maintenance_ticket",),
                server_name="fake_factory_mcp",
                server_version="test",
                protocol_version="test",
                tool_policies=(
                    ToolPolicy(
                        "create_maintenance_ticket",
                        operation=ToolOperation.WRITE,
                        requires_approval=True,
                    ),
                ),
            )

    provider = Provider()
    saver = InMemorySaver()

    async def verify():
        started, payload = await _agent(
            FakeLLMClient([_action_response()]), provider, saver
        ).astart_via_mcp("Create a maintenance ticket for S04.", thread_id=str(RUN_ID))
        assert started["pending_action"] is not None
        assert repo.tickets == ()
        await store.wait_for_approval(
            RUN_ID,
            {
                "action": payload["action"],
                "action_id": payload["action_id"],
                "arguments": payload["details"],
            },
            approval_execution_id=UUID(payload["approval_execution_id"]),
        )
        with pytest.raises(PermissionError):
            await _execute(server, "factory", context)
        await store.claim_resume(
            RUN_ID,
            decision="approve",
            approval_clearance=DataClassification.CONFIDENTIAL,
        )
        await _agent(
            FakeLLMClient([_final_response()]), provider, saver
        ).aresume_via_mcp(thread_id=str(RUN_ID), approval="approve")
        assert len(repo.tickets) == 1
        with pytest.raises(PermissionError):
            await _execute(server, "factory", context)

    asyncio.run(verify())

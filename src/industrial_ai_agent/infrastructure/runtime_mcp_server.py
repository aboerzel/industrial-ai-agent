"""Read-only MCP transport for bounded persisted Industrial Agent runtime facts."""

from __future__ import annotations

import argparse
import os
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from time import perf_counter
from typing import Annotated, Any, Literal
from uuid import UUID

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.context import Context
from mcp.types import ToolAnnotations
from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from industrial_ai_agent.application.mcp_access import McpPermission
from industrial_ai_agent.domain.security import DataClassification, SecurityContext
from industrial_ai_agent.infrastructure.api.postgres_run_store import (
    PostgreSqlAgentRunStore,
)
from industrial_ai_agent.infrastructure.api.run_store import (
    AgentRunStore,
    RecentRuntimeRunsQuery,
    RuntimeRunInspection,
)
from industrial_ai_agent.infrastructure.api.schemas import RunStatus
from industrial_ai_agent.infrastructure.mcp_access_control import (
    McpHttpAccessControl,
    create_demo_mcp_access_control,
    install_mcp_http_access_control,
)
from industrial_ai_agent.infrastructure.mcp_schema_validation import (
    require_strict_mcp_tool_arguments,
)
from industrial_ai_agent.infrastructure.persistence.postgres import (
    PostgreSqlSessionFactory,
)
from industrial_ai_agent.infrastructure.telemetry import (
    Telemetry,
    TelemetryConfiguration,
    configure_telemetry,
    run_instrumented_mcp_http_server,
    sanitized_error_code,
)

RUNTIME_MCP_SERVER_NAME = "runtime_mcp"
RUNTIME_MCP_SERVER_VERSION = "0.1.0"
RUNTIME_MCP_HTTP_PATH = "/mcp"

RunIdentifier = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        pattern=r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$",
    ),
]
RunStatusFilter = Literal[
    "running", "waiting_for_approval", "success", "limit_reached", "failed"
]
ClassificationFilter = Literal["PUBLIC", "INTERNAL", "CONFIDENTIAL", "RESTRICTED"]
ModelProfileFilter = Literal["local_fast", "local_quality", "public_fast"]
Lookback = Literal["15m", "1h", "6h", "24h"]

_RUNTIME_TOOL_PERMISSIONS = {
    "get_agent_run": McpPermission.READ_AGENT_RUNTIME,
    "get_run_tool_trajectory": McpPermission.READ_AGENT_RUNTIME,
    "get_run_approval": McpPermission.READ_AGENT_RUNTIME,
    "get_run_failure": McpPermission.READ_AGENT_RUNTIME,
    "list_recent_agent_runs": McpPermission.READ_AGENT_RUNTIME,
}
_TERMINAL_STATUSES = frozenset(
    {RunStatus.SUCCESS, RunStatus.LIMIT_REACHED, RunStatus.FAILED}
)
_TOOL_METADATA = {
    "list_stations": ("factory-mcp", "read", False),
    "get_station_overview": ("factory-mcp", "read", False),
    "list_products": ("factory-mcp", "read", False),
    "get_product_overview": ("factory-mcp", "read", False),
    "get_product_history": ("factory-mcp", "read", False),
    "get_machine_status": ("factory-mcp", "read", False),
    "search_documentation": ("knowledge-mcp", "read", False),
    "create_maintenance_ticket": ("factory-mcp", "write", True),
}
_LOOKBACKS = {
    "15m": timedelta(minutes=15),
    "1h": timedelta(hours=1),
    "6h": timedelta(hours=6),
    "24h": timedelta(hours=24),
}

type StoreForContext = Callable[[SecurityContext], AgentRunStore]


class _RunProjection(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    run_id: UUID
    status: RunStatus
    created_at: datetime | None
    updated_at: datetime | None
    classification: str
    run_profile: str
    model_profile: str | None
    thread_id: UUID
    tool_call_count: int = Field(ge=0)
    approval_state: Literal["none", "waiting", "approved", "rejected"]
    error_code: str | None
    terminal: bool


class _TrajectoryEntry(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    sequence: int = Field(ge=1)
    tool_name: Literal[
        "list_stations",
        "get_station_overview",
        "list_products",
        "get_product_overview",
        "get_product_history",
        "get_machine_status",
        "search_documentation",
        "create_maintenance_ticket",
    ]
    mcp_server: Literal["factory-mcp", "knowledge-mcp"]
    operation: Literal["read", "write"]
    approval_required: bool


class _ApprovalProjection(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    run_id: UUID
    approval_required: bool
    current_state: Literal["none", "waiting", "approved", "rejected"]
    action: Literal["create_maintenance_ticket"] | None
    decision: Literal["approve", "reject"] | None
    requested_at: datetime | None
    decided_at: datetime | None
    classification: str
    run_profile: str
    model_profile: str | None


class _FailureProjection(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    run_id: UUID
    failed: bool
    failure_status: RunStatus
    error_code: str | None


class _RecentRunProjection(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    run_id: UUID
    status: RunStatus
    created_at: datetime | None
    classification: str
    run_profile: str
    model_profile: str | None
    tool_call_count: int = Field(ge=0)
    approval_state: Literal["none", "waiting", "approved", "rejected"]
    terminal: bool


def create_runtime_mcp_server(
    *,
    store_for_context: StoreForContext,
    access_control: McpHttpAccessControl | None = None,
    telemetry: Telemetry | None = None,
) -> MCPServer:
    """Expose a fixed safe projection over RLS-filtered application run records."""
    server = MCPServer(
        name=RUNTIME_MCP_SERVER_NAME,
        version=RUNTIME_MCP_SERVER_VERSION,
        description="Read-only persisted Industrial Agent runtime facts for RCA.",
    )

    @server.tool(
        name="get_agent_run",
        description="Retrieve the safe persisted lifecycle projection for one run UUID.",
        structured_output=True,
        annotations=ToolAnnotations(read_only_hint=True),
    )
    async def get_agent_run(
        run_id: RunIdentifier, ctx: Context | None = None
    ) -> dict[str, Any]:
        inspection = await _lookup(run_id, ctx, access_control, store_for_context)
        return _invoke_tool(
            telemetry,
            "runtime.run.lookup",
            run_id,
            lambda: _RunProjection.model_validate(_run_payload(inspection)).model_dump(
                mode="json"
            ),
        )

    @server.tool(
        name="get_run_tool_trajectory",
        description="Retrieve ordered persisted tool names without arguments or results.",
        structured_output=True,
        annotations=ToolAnnotations(read_only_hint=True),
    )
    async def get_run_tool_trajectory(
        run_id: RunIdentifier, ctx: Context | None = None
    ) -> dict[str, Any]:
        inspection = await _lookup(run_id, ctx, access_control, store_for_context)
        return _invoke_tool(
            telemetry,
            "runtime.trajectory.lookup",
            run_id,
            lambda: {
                "run_id": str(inspection.run_id),
                "tool_call_count": inspection.tool_call_count,
                "trajectory": [
                    _TrajectoryEntry(
                        sequence=index,
                        tool_name=name,
                        mcp_server=_TOOL_METADATA[name][0],
                        operation=_TOOL_METADATA[name][1],
                        approval_required=_TOOL_METADATA[name][2],
                    ).model_dump(mode="json")
                    for index, name in enumerate(inspection.tool_names, start=1)
                ],
            },
        )

    @server.tool(
        name="get_run_approval",
        description="Retrieve safe persisted human-approval state and decision history.",
        structured_output=True,
        annotations=ToolAnnotations(read_only_hint=True),
    )
    async def get_run_approval(
        run_id: RunIdentifier, ctx: Context | None = None
    ) -> dict[str, Any]:
        inspection = await _lookup(run_id, ctx, access_control, store_for_context)
        return _invoke_tool(
            telemetry,
            "runtime.approval.lookup",
            run_id,
            lambda: _ApprovalProjection.model_validate(
                _approval_payload(inspection)
            ).model_dump(mode="json"),
        )

    @server.tool(
        name="get_run_failure",
        description="Retrieve safe persisted failure status and machine error code only.",
        structured_output=True,
        annotations=ToolAnnotations(read_only_hint=True),
    )
    async def get_run_failure(
        run_id: RunIdentifier, ctx: Context | None = None
    ) -> dict[str, Any]:
        inspection = await _lookup(run_id, ctx, access_control, store_for_context)
        return _invoke_tool(
            telemetry,
            "runtime.failure.lookup",
            run_id,
            lambda: _FailureProjection(
                run_id=inspection.run_id,
                failed=inspection.status is RunStatus.FAILED,
                failure_status=inspection.status,
                error_code=_safe_error_code(inspection.error_code),
            ).model_dump(mode="json"),
        )

    @server.tool(
        name="list_recent_agent_runs",
        description="List compact persisted run metadata over fixed bounded filters only.",
        structured_output=True,
        annotations=ToolAnnotations(read_only_hint=True),
    )
    async def list_recent_agent_runs(
        status: RunStatusFilter | None = None,
        classification: ClassificationFilter | None = None,
        model_profile: ModelProfileFilter | None = None,
        limit: Annotated[int, Field(ge=1, le=50)] = 20,
        lookback: Lookback = "1h",
        ctx: Context | None = None,
    ) -> dict[str, Any]:
        context = _context(ctx, access_control, "list_recent_agent_runs")
        query = RecentRuntimeRunsQuery(
            status=RunStatus(status) if status is not None else None,
            data_classification=DataClassification[classification]
            if classification is not None
            else None,
            model_profile=model_profile,
            created_after=datetime.now(UTC) - _LOOKBACKS[lookback],
            limit=limit,
        )
        records = await store_for_context(context.security_context).list_recent(query)
        return _invoke_tool(
            telemetry,
            "runtime.run.list",
            None,
            lambda: {
                "lookback": lookback,
                "limit": limit,
                "runs": [
                    _RecentRunProjection.model_validate(
                        _recent_payload(record)
                    ).model_dump(mode="json")
                    for record in records
                ],
            },
        )

    for tool_name in _RUNTIME_TOOL_PERMISSIONS:
        require_strict_mcp_tool_arguments(server, tool_name)
    if access_control is not None:
        install_mcp_http_access_control(server, access_control)
    return server


def create_secure_runtime_mcp_server(
    *, telemetry: Telemetry | None = None
) -> MCPServer:
    """Compose the HTTP service with ADR-015 access and RLS per MCP request."""
    database_url = os.getenv("AGENT_RUNTIME_DATABASE_URL") or os.getenv(
        "FACTORY_DATABASE_URL"
    )
    if not database_url:
        raise RuntimeError(
            "AGENT_RUNTIME_DATABASE_URL or FACTORY_DATABASE_URL is required"
        )
    session_factory = PostgreSqlSessionFactory(database_url)
    server: MCPServer

    async def listed_tools() -> list[Any]:
        return await server.list_tools()

    access_control = create_demo_mcp_access_control(
        tools=listed_tools,
        required_permission=lambda tool_name: _RUNTIME_TOOL_PERMISSIONS[tool_name],
    )
    server = create_runtime_mcp_server(
        store_for_context=lambda context: PostgreSqlAgentRunStore(
            session_factory, context
        ),
        access_control=access_control,
        telemetry=telemetry,
    )
    return server


def main() -> None:
    """Run the independent authenticated Streamable HTTP Runtime MCP service."""
    args = _parse_args()
    if args.transport == "stdio":
        raise RuntimeError(
            "Runtime MCP stdio composition requires an explicit run store"
        )
    telemetry = _create_telemetry()
    server = create_secure_runtime_mcp_server(telemetry=telemetry)
    run_instrumented_mcp_http_server(
        server,
        host=args.host,
        port=args.port,
        streamable_http_path=RUNTIME_MCP_HTTP_PATH,
        telemetry=telemetry,
    )


async def _lookup(
    run_id: str,
    ctx: Context | None,
    access_control: McpHttpAccessControl | None,
    store_for_context: StoreForContext,
) -> RuntimeRunInspection:
    context = _context(ctx, access_control, "get_agent_run")
    inspection = await store_for_context(context.security_context).inspect(UUID(run_id))
    if inspection is None:
        raise LookupError("Agent run was not found")
    return inspection


def _context(
    ctx: Context | None,
    access_control: McpHttpAccessControl | None,
    tool_name: str,
):
    if access_control is None:
        return type(
            "LocalAccess",
            (),
            {
                "security_context": SecurityContext(
                    subject_id="runtime-mcp-stdio",
                    roles=("runtime-mcp-stdio",),
                    clearance=DataClassification.CONFIDENTIAL,
                    authenticated=True,
                )
            },
        )()
    if ctx is None:
        raise PermissionError("MCP authentication failed")
    context = access_control.access_context_from_headers(ctx.headers)
    access_control.authorize_tool(context, tool_name)
    return context


def _run_payload(inspection: RuntimeRunInspection) -> dict[str, object]:
    return {
        "run_id": inspection.run_id,
        "status": inspection.status,
        "created_at": inspection.created_at,
        "updated_at": inspection.updated_at,
        "classification": inspection.data_classification.name,
        "run_profile": inspection.run_profile.value,
        "model_profile": inspection.model_profile,
        "thread_id": inspection.thread_id,
        "tool_call_count": inspection.tool_call_count,
        "approval_state": _approval_state(inspection),
        "error_code": _safe_error_code(inspection.error_code),
        "terminal": inspection.status in _TERMINAL_STATUSES,
    }


def _recent_payload(inspection: RuntimeRunInspection) -> dict[str, object]:
    return {
        "run_id": inspection.run_id,
        "status": inspection.status,
        "created_at": inspection.created_at,
        "classification": inspection.data_classification.name,
        "run_profile": inspection.run_profile.value,
        "model_profile": inspection.model_profile,
        "tool_call_count": inspection.tool_call_count,
        "approval_state": _approval_state(inspection),
        "terminal": inspection.status in _TERMINAL_STATUSES,
    }


def _approval_payload(inspection: RuntimeRunInspection) -> dict[str, object]:
    state = _approval_state(inspection)
    return {
        "run_id": inspection.run_id,
        "approval_required": inspection.approval_action is not None,
        "current_state": state,
        "action": inspection.approval_action,
        "decision": inspection.approval_decision,
        "requested_at": inspection.approval_requested_at,
        "decided_at": inspection.approval_decided_at,
        "classification": inspection.data_classification.name,
        "run_profile": inspection.run_profile.value,
        "model_profile": inspection.model_profile,
    }


def _approval_state(
    inspection: RuntimeRunInspection,
) -> Literal["none", "waiting", "approved", "rejected"]:
    if inspection.status is RunStatus.WAITING_FOR_APPROVAL:
        return "waiting"
    if inspection.approval_decision == "approve":
        return "approved"
    if inspection.approval_decision == "reject":
        return "rejected"
    return "none"


def _safe_error_code(value: object) -> str | None:
    if isinstance(value, str) and value.isidentifier() and len(value) <= 80:
        return value
    return None


def _invoke_tool(
    telemetry: Telemetry | None,
    span_name: str,
    run_id: str | None,
    action: Callable[[], dict[str, Any]],
) -> dict[str, Any]:
    if telemetry is None:
        return action()
    started = perf_counter()
    status = "success"
    attributes: dict[str, object] = {
        "mcp.tool": span_name,
        "mcp.operation": "read",
        "operation.type": "read",
    }
    if run_id is not None:
        attributes["run.id"] = run_id
    try:
        with telemetry.span(span_name, attributes):
            result = action()
        telemetry.log_event(event="mcp.server.completed", run_id=run_id)
        return result
    except BaseException as error:
        status = "failure"
        telemetry.log_error(
            event="mcp.server.failed",
            run_id=run_id,
            error_code=sanitized_error_code(error),
        )
        raise
    finally:
        telemetry.record_mcp_call(
            attributes={**attributes, "operation.status": status},
            duration_seconds=perf_counter() - started,
        )


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the read-only Runtime MCP server."
    )
    parser.add_argument(
        "--transport",
        choices=("stdio", "streamable-http"),
        default=os.getenv("RUNTIME_MCP_TRANSPORT", "streamable-http"),
    )
    parser.add_argument("--host", default=os.getenv("RUNTIME_MCP_HOST", "127.0.0.1"))
    parser.add_argument(
        "--port", type=int, default=int(os.getenv("RUNTIME_MCP_PORT", "8004"))
    )
    return parser.parse_args()


def _create_telemetry() -> Telemetry:
    return configure_telemetry(
        TelemetryConfiguration(
            enabled=os.getenv("OTEL_ENABLED", "false").strip().lower()
            in {"1", "true", "yes", "on"},
            otlp_endpoint=os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "127.0.0.1:4317"),
            service_name=os.getenv("OTEL_SERVICE_NAME", "runtime-mcp"),
        )
    )


if __name__ == "__main__":
    main()

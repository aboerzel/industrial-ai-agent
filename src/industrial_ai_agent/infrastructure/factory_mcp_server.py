"""MCP server adapter and deployment entry point for factory capabilities."""

import argparse
import os
from collections.abc import Callable
from time import perf_counter
from typing import Any

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.context import Context
from mcp.types import ToolAnnotations

from industrial_ai_agent.application.mcp_access import McpPermission
from industrial_ai_agent.domain.security import (
    DEMO_ENGINEER_SECURITY_CONTEXT,
    DataClassification,
    SecurityContext,
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
    McpHttpAccessControl,
    create_demo_mcp_access_control,
    install_mcp_http_access_control,
)
from industrial_ai_agent.infrastructure.mcp_schema_validation import (
    require_strict_mcp_tool_arguments,
)
from industrial_ai_agent.infrastructure.persistence.postgres import (
    PostgreSqlFactoryDiscoveryRepository,
    PostgreSqlMachineStatusRepository,
    PostgreSqlMaintenanceTicketRepository,
    PostgreSqlProductHistoryRepository,
    PostgreSqlSessionFactory,
)
from industrial_ai_agent.infrastructure.telemetry import (
    Telemetry,
    TelemetryConfiguration,
    configure_telemetry,
    run_instrumented_mcp_http_server,
    sanitized_error_code,
)
from industrial_ai_agent.tools.factory_discovery import FactoryDiscoveryCapability
from industrial_ai_agent.tools.machine_status import MachineStatusCapability
from industrial_ai_agent.tools.maintenance_ticket import MaintenanceTicketCapability
from industrial_ai_agent.tools.product_history import ProductHistoryCapability
from industrial_ai_agent.tools.tool_contracts import (
    MaintenanceSummary,
    MaintenanceTicketIdentifier,
    ProductIdentifier,
    StationIdentifier,
    ToolCallIdentifier,
)

FACTORY_MCP_SERVER_NAME = "factory_mcp"
FACTORY_MCP_SERVER_VERSION = "0.1.0"
FACTORY_MCP_HTTP_PATH = "/mcp"

_FACTORY_TOOL_PERMISSIONS = {
    "list_stations": McpPermission.READ_FACTORY,
    "get_station_overview": McpPermission.READ_FACTORY,
    "list_products": McpPermission.READ_FACTORY,
    "get_product_overview": McpPermission.READ_FACTORY,
    "get_product_history": McpPermission.READ_FACTORY,
    "get_machine_status": McpPermission.READ_FACTORY,
    "get_maintenance_ticket": McpPermission.READ_FACTORY,
    "create_maintenance_ticket": McpPermission.CREATE_MAINTENANCE_TICKET,
}

type FactoryCapabilitiesForContext = Callable[
    [SecurityContext],
    tuple[
        ProductHistoryCapability,
        MachineStatusCapability,
        FactoryDiscoveryCapability,
        MaintenanceTicketCapability | None,
    ],
]


def create_factory_mcp_server(
    *,
    product_history: ProductHistoryCapability,
    machine_status: MachineStatusCapability,
    factory_discovery: FactoryDiscoveryCapability,
    maintenance_ticket: MaintenanceTicketCapability | None = None,
    access_control: McpHttpAccessControl | None = None,
    capabilities_for_context: FactoryCapabilitiesForContext | None = None,
    telemetry: Telemetry | None = None,
) -> MCPServer:
    """Create an MCP adapter over the injected factory capabilities."""
    server = MCPServer(
        name=FACTORY_MCP_SERVER_NAME,
        version=FACTORY_MCP_SERVER_VERSION,
        description="Factory information and approved maintenance-action tools.",
    )

    @server.tool(
        name="list_stations",
        description="List stations visible to the authenticated factory clearance.",
        structured_output=True,
        annotations=ToolAnnotations(read_only_hint=True),
    )
    def list_stations(ctx: Context) -> dict[str, Any]:
        _, _, active_discovery, _ = _capabilities_for_request(
            ctx=ctx,
            tool_name="list_stations",
            fallback=(
                product_history,
                machine_status,
                factory_discovery,
                maintenance_ticket,
            ),
            access_control=access_control,
            capabilities_for_context=capabilities_for_context,
        )
        result = _invoke_factory_tool(
            telemetry=telemetry,
            tool_name="list_stations",
            operation_type="read",
            action=active_discovery.list_stations,
        )
        return result.model_dump(mode="json")

    @server.tool(
        name="get_station_overview",
        description="Get a bounded overview of one visible station and recent products.",
        structured_output=True,
        annotations=ToolAnnotations(read_only_hint=True),
    )
    def get_station_overview(
        station_id: StationIdentifier, ctx: Context
    ) -> dict[str, Any]:
        _, _, active_discovery, _ = _capabilities_for_request(
            ctx=ctx,
            tool_name="get_station_overview",
            fallback=(
                product_history,
                machine_status,
                factory_discovery,
                maintenance_ticket,
            ),
            access_control=access_control,
            capabilities_for_context=capabilities_for_context,
        )
        result = _invoke_factory_tool(
            telemetry=telemetry,
            tool_name="get_station_overview",
            operation_type="read",
            action=lambda: active_discovery.get_station_overview(station_id),
        )
        return result.model_dump(mode="json")

    @server.tool(
        name="list_products",
        description="List products visible to the authenticated factory clearance.",
        structured_output=True,
        annotations=ToolAnnotations(read_only_hint=True),
    )
    def list_products(ctx: Context) -> dict[str, Any]:
        _, _, active_discovery, _ = _capabilities_for_request(
            ctx=ctx,
            tool_name="list_products",
            fallback=(
                product_history,
                machine_status,
                factory_discovery,
                maintenance_ticket,
            ),
            access_control=access_control,
            capabilities_for_context=capabilities_for_context,
        )
        result = _invoke_factory_tool(
            telemetry=telemetry,
            tool_name="list_products",
            operation_type="read",
            action=active_discovery.list_products,
        )
        return result.model_dump(mode="json")

    @server.tool(
        name="get_product_overview",
        description="Get a bounded overview of one visible product.",
        structured_output=True,
        annotations=ToolAnnotations(read_only_hint=True),
    )
    def get_product_overview(
        product_id: ProductIdentifier, ctx: Context
    ) -> dict[str, Any]:
        _, _, active_discovery, _ = _capabilities_for_request(
            ctx=ctx,
            tool_name="get_product_overview",
            fallback=(
                product_history,
                machine_status,
                factory_discovery,
                maintenance_ticket,
            ),
            access_control=access_control,
            capabilities_for_context=capabilities_for_context,
        )
        result = _invoke_factory_tool(
            telemetry=telemetry,
            tool_name="get_product_overview",
            operation_type="read",
            action=lambda: active_discovery.get_product_overview(product_id),
        )
        return result.model_dump(mode="json")

    @server.tool(
        name="get_product_history",
        description="Get historical production information for a product ID.",
        structured_output=True,
        annotations=ToolAnnotations(read_only_hint=True),
    )
    def get_product_history(
        product_id: ProductIdentifier, ctx: Context
    ) -> dict[str, Any]:
        active_product_history, _, _, _ = _capabilities_for_request(
            ctx=ctx,
            tool_name="get_product_history",
            fallback=(
                product_history,
                machine_status,
                factory_discovery,
                maintenance_ticket,
            ),
            access_control=access_control,
            capabilities_for_context=capabilities_for_context,
        )
        result = _invoke_factory_tool(
            telemetry=telemetry,
            tool_name="get_product_history",
            operation_type="read",
            action=lambda: active_product_history.get_product_history(product_id),
        )
        return result.model_dump(mode="json")

    @server.tool(
        name="get_machine_status",
        description="Get the current operating state of a station ID.",
        structured_output=True,
        annotations=ToolAnnotations(read_only_hint=True),
    )
    def get_machine_status(
        station_id: StationIdentifier, ctx: Context
    ) -> dict[str, Any]:
        _, active_machine_status, _, _ = _capabilities_for_request(
            ctx=ctx,
            tool_name="get_machine_status",
            fallback=(
                product_history,
                machine_status,
                factory_discovery,
                maintenance_ticket,
            ),
            access_control=access_control,
            capabilities_for_context=capabilities_for_context,
        )
        result = _invoke_factory_tool(
            telemetry=telemetry,
            tool_name="get_machine_status",
            operation_type="read",
            action=lambda: active_machine_status.get_machine_status(station_id),
        )
        return result.model_dump(mode="json")

    if maintenance_ticket is not None:
        ticket_capability = maintenance_ticket

        @server.tool(
            name="get_maintenance_ticket",
            description="Get the bounded visible details of one maintenance ticket.",
            structured_output=True,
            annotations=ToolAnnotations(read_only_hint=True),
        )
        def get_maintenance_ticket(
            ticket_id: MaintenanceTicketIdentifier, ctx: Context
        ) -> dict[str, Any]:
            _, _, _, active_ticket_capability = _capabilities_for_request(
                ctx=ctx,
                tool_name="get_maintenance_ticket",
                fallback=(
                    product_history,
                    machine_status,
                    factory_discovery,
                    ticket_capability,
                ),
                access_control=access_control,
                capabilities_for_context=capabilities_for_context,
            )
            if active_ticket_capability is None:
                raise PermissionError("MCP tool is not authorized")
            result = _invoke_factory_tool(
                telemetry=telemetry,
                tool_name="get_maintenance_ticket",
                operation_type="read",
                action=lambda: active_ticket_capability.get_maintenance_ticket(
                    ticket_id
                ),
            )
            return result.model_dump(mode="json")

        @server.tool(
            name="create_maintenance_ticket",
            description="Create an approved maintenance ticket for a station.",
            structured_output=True,
            annotations=ToolAnnotations(
                read_only_hint=False,
                destructive_hint=False,
                idempotent_hint=True,
            ),
        )
        def create_maintenance_ticket(
            station_id: StationIdentifier,
            summary: MaintenanceSummary,
            request_id: ToolCallIdentifier,
            ctx: Context,
        ) -> dict[str, Any]:
            _, _, _, active_ticket_capability = _capabilities_for_request(
                ctx=ctx,
                tool_name="create_maintenance_ticket",
                fallback=(
                    product_history,
                    machine_status,
                    factory_discovery,
                    ticket_capability,
                ),
                access_control=access_control,
                capabilities_for_context=capabilities_for_context,
            )
            if active_ticket_capability is None:
                raise PermissionError("MCP tool is not authorized")
            result = _invoke_factory_tool(
                telemetry=telemetry,
                tool_name="create_maintenance_ticket",
                operation_type="write",
                action=lambda: active_ticket_capability.create_maintenance_ticket(
                    request_id=request_id,
                    station_id=station_id,
                    summary=summary,
                ),
            )
            return result.model_dump(mode="json")

    for tool_name in (
        "list_stations",
        "get_station_overview",
        "list_products",
        "get_product_overview",
        "get_product_history",
        "get_machine_status",
    ):
        require_strict_mcp_tool_arguments(server, tool_name)
    if maintenance_ticket is not None:
        require_strict_mcp_tool_arguments(server, "get_maintenance_ticket")
        require_strict_mcp_tool_arguments(server, "create_maintenance_ticket")

    if access_control is not None:
        install_mcp_http_access_control(server, access_control)

    return server


def create_default_factory_mcp_server(
    *, telemetry: Telemetry | None = None
) -> MCPServer:
    """Build the persistent service when configured, retaining in-memory stdio tests."""
    database_url = os.getenv("FACTORY_DATABASE_URL")
    if database_url:
        session_factory = PostgreSqlSessionFactory(database_url)
        return create_factory_mcp_server(
            product_history=ProductHistoryCapability(
                PostgreSqlProductHistoryRepository(
                    session_factory, DEMO_ENGINEER_SECURITY_CONTEXT
                )
            ),
            machine_status=MachineStatusCapability(
                PostgreSqlMachineStatusRepository(
                    session_factory, DEMO_ENGINEER_SECURITY_CONTEXT
                )
            ),
            factory_discovery=FactoryDiscoveryCapability(
                PostgreSqlFactoryDiscoveryRepository(
                    session_factory, DEMO_ENGINEER_SECURITY_CONTEXT
                )
            ),
            maintenance_ticket=MaintenanceTicketCapability(
                PostgreSqlMaintenanceTicketRepository(
                    session_factory, DEMO_ENGINEER_SECURITY_CONTEXT
                )
            ),
            telemetry=telemetry,
        )
    return create_factory_mcp_server(
        product_history=ProductHistoryCapability(InMemoryProductHistoryRepository()),
        machine_status=MachineStatusCapability(InMemoryMachineStatusRepository()),
        factory_discovery=FactoryDiscoveryCapability(
            InMemoryFactoryDiscoveryRepository()
        ),
        maintenance_ticket=MaintenanceTicketCapability(
            InMemoryMaintenanceTicketRepository()
        ),
        telemetry=telemetry,
    )


def create_secure_factory_mcp_server(
    *, telemetry: Telemetry | None = None
) -> MCPServer:
    """Build the HTTP composition with request-derived RLS clearance."""
    database_url = os.getenv("FACTORY_DATABASE_URL")
    if not database_url:
        raise RuntimeError("FACTORY_DATABASE_URL is required for secure HTTP MCP")
    session_factory = PostgreSqlSessionFactory(database_url)

    def capabilities_for_context(security_context: SecurityContext):
        return (
            ProductHistoryCapability(
                PostgreSqlProductHistoryRepository(session_factory, security_context)
            ),
            MachineStatusCapability(
                PostgreSqlMachineStatusRepository(session_factory, security_context)
            ),
            FactoryDiscoveryCapability(
                PostgreSqlFactoryDiscoveryRepository(session_factory, security_context)
            ),
            MaintenanceTicketCapability(
                PostgreSqlMaintenanceTicketRepository(session_factory, security_context)
            ),
        )

    # Authenticated handlers replace these with request-derived capabilities.
    # Keep the inert composition fallback at the minimum clearance as defense in depth.
    (
        placeholder_product_history,
        placeholder_machine_status,
        placeholder_factory_discovery,
        placeholder_ticket,
    ) = capabilities_for_context(
        SecurityContext(
            subject_id="secure-http-fallback",
            roles=("fallback",),
            clearance=DataClassification.PUBLIC,
            authenticated=False,
        )
    )
    server: MCPServer
    access_control: McpHttpAccessControl

    # The closure is evaluated only after the server has been assigned.
    async def listed_tools():
        return await server.list_tools()

    access_control = create_demo_mcp_access_control(
        tools=listed_tools,
        required_permission=_required_factory_permission,
    )
    server = create_factory_mcp_server(
        product_history=placeholder_product_history,
        machine_status=placeholder_machine_status,
        factory_discovery=placeholder_factory_discovery,
        maintenance_ticket=placeholder_ticket,
        access_control=access_control,
        capabilities_for_context=capabilities_for_context,
        telemetry=telemetry,
    )
    return server


def main() -> None:
    """Run the demo server through the transport chosen at process startup."""
    args = _parse_args()
    telemetry = _create_factory_telemetry() if args.transport != "stdio" else None
    server = (
        create_default_factory_mcp_server(telemetry=telemetry)
        if args.transport == "stdio"
        else create_secure_factory_mcp_server(telemetry=telemetry)
    )
    if args.transport == "stdio":
        server.run(transport="stdio")
        return
    assert telemetry is not None
    run_instrumented_mcp_http_server(
        server,
        host=args.host,
        port=args.port,
        streamable_http_path=FACTORY_MCP_HTTP_PATH,
        telemetry=telemetry,
    )


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the factory MCP server.")
    parser.add_argument(
        "--transport",
        choices=("stdio", "streamable-http"),
        default=os.getenv("FACTORY_MCP_TRANSPORT", "stdio"),
    )
    parser.add_argument("--host", default=os.getenv("FACTORY_MCP_HOST", "127.0.0.1"))
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.getenv("FACTORY_MCP_PORT", "8001")),
    )
    return parser.parse_args()


def _required_factory_permission(tool_name: str) -> McpPermission:
    return _FACTORY_TOOL_PERMISSIONS[tool_name]


def _create_factory_telemetry() -> Telemetry:
    return configure_telemetry(
        TelemetryConfiguration(
            enabled=os.getenv("OTEL_ENABLED", "false").strip().lower()
            in {"1", "true", "yes", "on"},
            otlp_endpoint=os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "127.0.0.1:4317"),
            service_name=os.getenv("OTEL_SERVICE_NAME", "factory-mcp"),
        )
    )


def _invoke_factory_tool(
    *,
    telemetry: Telemetry | None,
    tool_name: str,
    operation_type: str,
    action: Callable[[], Any],
) -> Any:
    if telemetry is None:
        return action()
    attributes = {
        "mcp.tool": tool_name,
        "mcp.operation": operation_type,
        "operation.type": operation_type,
    }
    started = perf_counter()
    status = "success"
    try:
        with telemetry.span("factory.tool", attributes) as span:
            result = action()
            classification = getattr(result, "classification", None)
            if isinstance(classification, DataClassification):
                telemetry.set_span_attributes(
                    span, {"data.classification": classification.name}
                )
        telemetry.log_event(event="mcp.server.completed", run_id=None)
        return result
    except BaseException as error:
        status = "failure"
        telemetry.log_error(
            event="mcp.server.failed",
            run_id=None,
            error_code=sanitized_error_code(error),
        )
        raise
    finally:
        telemetry.record_mcp_call(
            attributes={**attributes, "operation.status": status},
            duration_seconds=perf_counter() - started,
        )


def _capabilities_for_request(
    *,
    ctx: Context | None,
    tool_name: str,
    fallback: tuple[
        ProductHistoryCapability,
        MachineStatusCapability,
        FactoryDiscoveryCapability,
        MaintenanceTicketCapability | None,
    ],
    access_control: McpHttpAccessControl | None,
    capabilities_for_context: FactoryCapabilitiesForContext | None,
) -> tuple[
    ProductHistoryCapability,
    MachineStatusCapability,
    FactoryDiscoveryCapability,
    MaintenanceTicketCapability | None,
]:
    if access_control is None or capabilities_for_context is None:
        return fallback
    if ctx is None:
        raise PermissionError("MCP authentication failed")
    access_context = access_control.access_context_from_headers(ctx.headers)
    access_control.authorize_tool(access_context, tool_name)
    return capabilities_for_context(access_context.security_context)


if __name__ == "__main__":
    main()

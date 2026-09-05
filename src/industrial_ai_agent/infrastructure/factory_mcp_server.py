"""MCP server adapter and deployment entry point for factory capabilities."""

import argparse
import os
from collections.abc import Callable
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
    PostgreSqlMachineStatusRepository,
    PostgreSqlMaintenanceTicketRepository,
    PostgreSqlProductHistoryRepository,
    PostgreSqlSessionFactory,
)
from industrial_ai_agent.tools.machine_status import MachineStatusCapability
from industrial_ai_agent.tools.maintenance_ticket import MaintenanceTicketCapability
from industrial_ai_agent.tools.product_history import ProductHistoryCapability
from industrial_ai_agent.tools.tool_contracts import (
    MaintenanceSummary,
    ProductIdentifier,
    StationIdentifier,
    ToolCallIdentifier,
)

FACTORY_MCP_SERVER_NAME = "factory_mcp"
FACTORY_MCP_SERVER_VERSION = "0.1.0"
FACTORY_MCP_HTTP_PATH = "/mcp"

_FACTORY_TOOL_PERMISSIONS = {
    "get_product_history": McpPermission.READ_FACTORY,
    "get_machine_status": McpPermission.READ_FACTORY,
    "create_maintenance_ticket": McpPermission.CREATE_MAINTENANCE_TICKET,
}

type FactoryCapabilitiesForContext = Callable[
    [SecurityContext],
    tuple[
        ProductHistoryCapability,
        MachineStatusCapability,
        MaintenanceTicketCapability | None,
    ],
]


def create_factory_mcp_server(
    *,
    product_history: ProductHistoryCapability,
    machine_status: MachineStatusCapability,
    maintenance_ticket: MaintenanceTicketCapability | None = None,
    access_control: McpHttpAccessControl | None = None,
    capabilities_for_context: FactoryCapabilitiesForContext | None = None,
) -> MCPServer:
    """Create an MCP adapter over the injected factory capabilities."""
    server = MCPServer(
        name=FACTORY_MCP_SERVER_NAME,
        version=FACTORY_MCP_SERVER_VERSION,
        description="Factory information and approved maintenance-action tools.",
    )

    @server.tool(
        name="get_product_history",
        description="Get historical production information for a product ID.",
        structured_output=True,
        annotations=ToolAnnotations(read_only_hint=True),
    )
    def get_product_history(
        product_id: ProductIdentifier, ctx: Context
    ) -> dict[str, Any]:
        active_product_history, _, _ = _capabilities_for_request(
            ctx=ctx,
            tool_name="get_product_history",
            fallback=(product_history, machine_status, maintenance_ticket),
            access_control=access_control,
            capabilities_for_context=capabilities_for_context,
        )
        result = active_product_history.get_product_history(product_id)
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
        _, active_machine_status, _ = _capabilities_for_request(
            ctx=ctx,
            tool_name="get_machine_status",
            fallback=(product_history, machine_status, maintenance_ticket),
            access_control=access_control,
            capabilities_for_context=capabilities_for_context,
        )
        result = active_machine_status.get_machine_status(station_id)
        return result.model_dump(mode="json")

    if maintenance_ticket is not None:
        ticket_capability = maintenance_ticket

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
            _, _, active_ticket_capability = _capabilities_for_request(
                ctx=ctx,
                tool_name="create_maintenance_ticket",
                fallback=(product_history, machine_status, ticket_capability),
                access_control=access_control,
                capabilities_for_context=capabilities_for_context,
            )
            if active_ticket_capability is None:
                raise PermissionError("MCP tool is not authorized")
            result = active_ticket_capability.create_maintenance_ticket(
                request_id=request_id,
                station_id=station_id,
                summary=summary,
            )
            return result.model_dump(mode="json")

    for tool_name in ("get_product_history", "get_machine_status"):
        require_strict_mcp_tool_arguments(server, tool_name)
    if maintenance_ticket is not None:
        require_strict_mcp_tool_arguments(server, "create_maintenance_ticket")

    if access_control is not None:
        install_mcp_http_access_control(server, access_control)

    return server


def create_default_factory_mcp_server() -> MCPServer:
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
            maintenance_ticket=MaintenanceTicketCapability(
                PostgreSqlMaintenanceTicketRepository(
                    session_factory, DEMO_ENGINEER_SECURITY_CONTEXT
                )
            ),
        )
    return create_factory_mcp_server(
        product_history=ProductHistoryCapability(InMemoryProductHistoryRepository()),
        machine_status=MachineStatusCapability(InMemoryMachineStatusRepository()),
        maintenance_ticket=MaintenanceTicketCapability(
            InMemoryMaintenanceTicketRepository()
        ),
    )


def create_secure_factory_mcp_server() -> MCPServer:
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
            MaintenanceTicketCapability(
                PostgreSqlMaintenanceTicketRepository(session_factory, security_context)
            ),
        )

    # Authenticated handlers replace these with request-derived capabilities.
    # Keep the inert composition fallback at the minimum clearance as defense in depth.
    placeholder_product_history, placeholder_machine_status, placeholder_ticket = (
        capabilities_for_context(
            SecurityContext(
                subject_id="secure-http-fallback",
                roles=("fallback",),
                clearance=DataClassification.PUBLIC,
                authenticated=False,
            )
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
        maintenance_ticket=placeholder_ticket,
        access_control=access_control,
        capabilities_for_context=capabilities_for_context,
    )
    return server


def main() -> None:
    """Run the demo server through the transport chosen at process startup."""
    args = _parse_args()
    server = (
        create_default_factory_mcp_server()
        if args.transport == "stdio"
        else create_secure_factory_mcp_server()
    )
    if args.transport == "stdio":
        server.run(transport="stdio")
        return
    server.run(
        transport="streamable-http",
        host=args.host,
        port=args.port,
        streamable_http_path=FACTORY_MCP_HTTP_PATH,
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


def _capabilities_for_request(
    *,
    ctx: Context | None,
    tool_name: str,
    fallback: tuple[
        ProductHistoryCapability,
        MachineStatusCapability,
        MaintenanceTicketCapability | None,
    ],
    access_control: McpHttpAccessControl | None,
    capabilities_for_context: FactoryCapabilitiesForContext | None,
) -> tuple[
    ProductHistoryCapability,
    MachineStatusCapability,
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

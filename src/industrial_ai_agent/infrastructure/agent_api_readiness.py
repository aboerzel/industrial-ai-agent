"""Operational readiness checks for the deployed Agent API."""

import os
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from industrial_ai_agent.infrastructure.factory_mcp_client import (
    McpTransport,
    StreamableHttpServerParameters,
)
from industrial_ai_agent.infrastructure.mcp_readiness import probe_mcp_readiness

FACTORY_REQUIRED_TOOL_NAMES = frozenset(
    {
        "list_stations",
        "get_station_overview",
        "list_products",
        "get_product_overview",
        "get_product_history",
        "get_machine_status",
        "get_maintenance_ticket",
        "create_maintenance_ticket",
    }
)
KNOWLEDGE_REQUIRED_TOOL_NAMES = frozenset({"search_documentation"})
HARDWARE_REQUIRED_TOOL_NAMES = frozenset(
    {
        "get_position_reference_status",
        "prepare_reference_calibration",
        "execute_reference_calibration",
    }
)


class AgentApiReadinessError(RuntimeError):
    """The API process is alive but cannot serve its declared MCP capabilities."""


@dataclass(frozen=True, slots=True)
class RequiredMcpService:
    """One MCP service required by the normal Agent API runtime."""

    service_id: str
    transport: McpTransport
    required_tool_names: frozenset[str]


McpReadinessProbe = Callable[..., Awaitable[object]]


async def check_required_mcp_services(
    services: tuple[RequiredMcpService, ...],
    *,
    probe: McpReadinessProbe = probe_mcp_readiness,
) -> None:
    """Confirm every required MCP service through initialize and tools/list."""
    for service in services:
        try:
            await probe(
                service.transport,
                required_tool_names=service.required_tool_names,
            )
        except Exception as error:
            raise AgentApiReadinessError(
                f"Required MCP service is not ready: {service.service_id}"
            ) from error


def create_default_agent_api_readiness_check() -> Callable[[], Awaitable[None]]:
    """Build the Compose deployment's dependency-aware readiness check."""
    token = os.getenv("MCP_INDUSTRIAL_AGENT_TOKEN")
    if token is None or not token.strip():
        raise RuntimeError(
            "MCP_INDUSTRIAL_AGENT_TOKEN is required for Agent API readiness"
        )
    services = (
        RequiredMcpService(
            service_id="factory",
            transport=StreamableHttpServerParameters(
                url=os.getenv("FACTORY_MCP_URL", "http://127.0.0.1:8001/mcp"),
                bearer_token=token,
            ),
            required_tool_names=FACTORY_REQUIRED_TOOL_NAMES,
        ),
        RequiredMcpService(
            service_id="knowledge",
            transport=StreamableHttpServerParameters(
                url=os.getenv("KNOWLEDGE_MCP_URL", "http://127.0.0.1:8002/mcp"),
                bearer_token=token,
            ),
            required_tool_names=KNOWLEDGE_REQUIRED_TOOL_NAMES,
        ),
        RequiredMcpService(
            service_id="hardware",
            transport=StreamableHttpServerParameters(
                url=os.getenv("HARDWARE_MCP_URL", "http://127.0.0.1:8006/mcp"),
                bearer_token=token,
            ),
            required_tool_names=HARDWARE_REQUIRED_TOOL_NAMES,
        ),
    )

    async def check() -> None:
        await check_required_mcp_services(services)

    return check

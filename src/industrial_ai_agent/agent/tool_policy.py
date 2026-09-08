"""Deterministic authorization metadata for agent-visible MCP tools."""

from dataclasses import dataclass
from enum import StrEnum


class ToolOperation(StrEnum):
    READ = "read"
    WRITE = "write"


@dataclass(frozen=True, slots=True)
class ToolPolicy:
    """Authorization and side-effect properties independent of tool names."""

    name: str
    operation: ToolOperation
    requires_approval: bool = False

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("Tool policy name must not be empty")
        if self.operation is ToolOperation.READ and self.requires_approval:
            raise ValueError("Read tools must not require approval")
        if self.operation is ToolOperation.WRITE and not self.requires_approval:
            raise ValueError("Write tools must require approval")


TROUBLESHOOTING_TOOL_POLICIES = {
    policy.name: policy
    for policy in (
        ToolPolicy("list_stations", ToolOperation.READ),
        ToolPolicy("get_station_overview", ToolOperation.READ),
        ToolPolicy("list_products", ToolOperation.READ),
        ToolPolicy("get_product_overview", ToolOperation.READ),
        ToolPolicy("get_product_history", ToolOperation.READ),
        ToolPolicy("get_machine_status", ToolOperation.READ),
        ToolPolicy("get_maintenance_ticket", ToolOperation.READ),
        ToolPolicy("search_documentation", ToolOperation.READ),
        ToolPolicy(
            "create_maintenance_ticket",
            ToolOperation.WRITE,
            requires_approval=True,
        ),
    )
}


def get_troubleshooting_tool_policy(name: str) -> ToolPolicy:
    """Return the fixed policy for a tool or reject it before it is bindable."""
    try:
        return TROUBLESHOOTING_TOOL_POLICIES[name]
    except KeyError as error:
        raise ValueError(
            f"No troubleshooting policy is defined for tool: {name}"
        ) from error

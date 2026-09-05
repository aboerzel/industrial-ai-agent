"""Strict, provider-independent argument contracts for agent-facing tools."""

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

ProductIdentifier = Annotated[
    str,
    StringConstraints(strip_whitespace=True, pattern=r"^P[0-9]{4,}$"),
]
StationIdentifier = Annotated[
    str,
    StringConstraints(strip_whitespace=True, pattern=r"^S[0-9]{2,3}$"),
]
ToolCallIdentifier = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=128),
]
MaintenanceSummary = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=500),
]
DocumentationQuery = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=500),
]
DocumentationResultLimit = Annotated[int, Field(ge=1, le=5)]


class _StrictToolArguments(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)


class GetProductHistoryArguments(_StrictToolArguments):
    product_id: ProductIdentifier


class GetMachineStatusArguments(_StrictToolArguments):
    station_id: StationIdentifier


class SearchDocumentationArguments(_StrictToolArguments):
    query: DocumentationQuery
    top_k: DocumentationResultLimit = 3


class CreateMaintenanceTicketProposalArguments(_StrictToolArguments):
    """Arguments visible to the model before human approval."""

    station_id: StationIdentifier
    summary: MaintenanceSummary


class CreateMaintenanceTicketExecutionArguments(
    CreateMaintenanceTicketProposalArguments
):
    """MCP execution contract; request_id is injected only after approval."""

    request_id: ToolCallIdentifier

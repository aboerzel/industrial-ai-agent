"""Public FastAPI request and response contracts."""

from enum import StrEnum
from typing import Annotated
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    StringConstraints,
    field_validator,
)

from industrial_ai_agent.agent.response_language import ResponseLanguage


class RunStatus(StrEnum):
    RUNNING = "running"
    WAITING_FOR_APPROVAL = "waiting_for_approval"
    SUCCESS = "success"
    LIMIT_REACHED = "limit_reached"
    FAILED = "failed"


class DemoUserClearance(StrEnum):
    """Closed UI contract for the local demo authn/authz simulation."""

    PUBLIC = "PUBLIC"
    INTERNAL = "INTERNAL"
    CONFIDENTIAL = "CONFIDENTIAL"
    RESTRICTED = "RESTRICTED"


class DataClassificationLabel(StrEnum):
    """Public projection of a server-resolved run classification."""

    PUBLIC = "PUBLIC"
    INTERNAL = "INTERNAL"
    CONFIDENTIAL = "CONFIDENTIAL"
    RESTRICTED = "RESTRICTED"


class ApiErrorResponse(BaseModel):
    """Sanitized public error; never a provider exception projection."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    code: Annotated[str, StringConstraints(min_length=1, max_length=80)]
    message: Annotated[str, StringConstraints(min_length=1, max_length=500)]


class HealthResponse(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    status: str = "ok"


class CreateRunRequest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    message: Annotated[str, StringConstraints(min_length=1, max_length=4_000)] = Field(
        description="Troubleshooting request for the industrial agent."
    )
    user_clearance: DemoUserClearance = Field(
        default=DemoUserClearance.PUBLIC,
        description="Demo-only simulated user clearance; it never sets run classification.",
    )
    response_language: ResponseLanguage | None = Field(
        default=None,
        description=(
            "Explicit response language for this run. When omitted, the server uses "
            "deterministic request-language detection."
        ),
    )
    investigation_id: UUID | None = Field(
        default=None,
        description="Optional existing investigation grouping; never conveys authorization.",
    )

    @field_validator("message")
    @classmethod
    def validate_message(cls, message: str) -> str:
        normalized_message = message.strip()
        if not normalized_message:
            raise ValueError("message must not be empty")
        return normalized_message


class InternalDiagnosticRequest(BaseModel):
    """Bounded source references; no free text can enter the INTERNAL path."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    product_id: Annotated[str, StringConstraints(pattern=r"^P[0-9]{4}$", strict=True)]
    station_id: Annotated[str, StringConstraints(pattern=r"^S[0-9]{2}$", strict=True)]


class PublicToolName(StrEnum):
    LIST_STATIONS = "list_stations"
    GET_STATION_OVERVIEW = "get_station_overview"
    LIST_PRODUCTS = "list_products"
    GET_PRODUCT_OVERVIEW = "get_product_overview"
    GET_PRODUCT_HISTORY = "get_product_history"
    GET_MACHINE_STATUS = "get_machine_status"
    GET_MAINTENANCE_TICKET = "get_maintenance_ticket"
    SEARCH_DOCUMENTATION = "search_documentation"
    CREATE_MAINTENANCE_TICKET = "create_maintenance_ticket"


class ToolCallResponse(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    tool: PublicToolName
    arguments: dict[str, JsonValue]


class InvestigationStepResponse(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    step: int = Field(ge=1, le=4)
    action: PublicToolName
    finding: Annotated[str, StringConstraints(min_length=1, max_length=1_000)]


class IdentifierTypeResponse(StrEnum):
    ERROR_CODE = "error_code"
    STATION = "station"
    PRODUCT = "product"
    MAINTENANCE_TICKET = "maintenance_ticket"


class IdentifierReferenceResponse(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    value: Annotated[str, StringConstraints(min_length=2, max_length=64)]
    type: IdentifierTypeResponse


class DocumentReferenceResponse(BaseModel):
    """Authorized retrieval metadata; it deliberately has no storage location."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    document_id: Annotated[str, StringConstraints(min_length=1, max_length=128)]
    title: Annotated[str, StringConstraints(min_length=1, max_length=256)]
    format: Annotated[str, StringConstraints(min_length=1, max_length=64)]


class ApprovalRequestResponse(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    action: PublicToolName
    summary: Annotated[str, StringConstraints(min_length=1, max_length=500)]
    arguments: dict[str, JsonValue]
    classification: Annotated[str, StringConstraints(min_length=1, max_length=32)]
    model_profile: Annotated[str, StringConstraints(min_length=1, max_length=128)]
    status: RunStatus
    created_at: str


class ResumeDecision(StrEnum):
    APPROVE = "approve"
    REJECT = "reject"


class ResumeRunRequest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    decision: ResumeDecision


class RunResponse(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    run_id: UUID
    investigation_id: UUID
    investigation_sequence: int = Field(ge=1)
    status: RunStatus
    data_classification: DataClassificationLabel
    answer: Annotated[str, StringConstraints(max_length=8_000)] | None = None
    investigation_steps: tuple[InvestigationStepResponse, ...] = Field(
        default=(), max_length=4
    )
    next_steps: tuple[
        Annotated[str, StringConstraints(min_length=1, max_length=500)], ...
    ] = Field(default=(), max_length=5)
    identifiers: tuple[IdentifierReferenceResponse, ...] = Field(
        default=(), max_length=12
    )
    documents: tuple[DocumentReferenceResponse, ...] = Field(default=(), max_length=5)
    tool_calls: tuple[ToolCallResponse, ...] = ()
    error: ApiErrorResponse | None = None
    approval_request: ApprovalRequestResponse | None = None


class InvestigationTurnResponse(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    run_id: UUID
    sequence: int = Field(ge=1)
    status: RunStatus
    data_classification: DataClassificationLabel
    response_language: str
    request: Annotated[str, StringConstraints(max_length=4_000)]
    answer: Annotated[str, StringConstraints(max_length=8_000)] | None = None
    investigation_steps: tuple[InvestigationStepResponse, ...] = Field(
        default=(), max_length=4
    )
    next_steps: tuple[
        Annotated[str, StringConstraints(min_length=1, max_length=500)], ...
    ] = Field(default=(), max_length=5)
    identifiers: tuple[IdentifierReferenceResponse, ...] = Field(
        default=(), max_length=12
    )
    documents: tuple[DocumentReferenceResponse, ...] = Field(default=(), max_length=5)
    tool_calls: tuple[ToolCallResponse, ...] = ()
    error: ApiErrorResponse | None = None
    created_at: str | None = None
    updated_at: str | None = None
    approval_request: ApprovalRequestResponse | None = None


class InvestigationResponse(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    investigation_id: UUID
    created_at: str | None = None
    run_count: int = Field(ge=0)
    tool_call_count: int = Field(ge=0)
    status: str
    turns: tuple[InvestigationTurnResponse, ...]

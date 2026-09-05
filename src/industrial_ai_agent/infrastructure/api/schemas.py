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


class RunStatus(StrEnum):
    RUNNING = "running"
    WAITING_FOR_APPROVAL = "waiting_for_approval"
    SUCCESS = "success"
    LIMIT_REACHED = "limit_reached"
    FAILED = "failed"


class HealthResponse(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    status: str = "ok"


class CreateRunRequest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    message: Annotated[str, StringConstraints(min_length=1, max_length=4_000)] = Field(
        description="Troubleshooting request for the industrial agent."
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

    product_id: Annotated[
        str, StringConstraints(pattern=r"^P[0-9]{4}$", strict=True)
    ]
    station_id: Annotated[
        str, StringConstraints(pattern=r"^S[0-9]{2}$", strict=True)
    ]


class PublicToolName(StrEnum):
    GET_PRODUCT_HISTORY = "get_product_history"
    GET_MACHINE_STATUS = "get_machine_status"
    SEARCH_DOCUMENTATION = "search_documentation"
    CREATE_MAINTENANCE_TICKET = "create_maintenance_ticket"


class ToolCallResponse(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    tool: PublicToolName
    arguments: dict[str, JsonValue]


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
    status: RunStatus
    answer: Annotated[str, StringConstraints(max_length=8_000)] | None = None
    tool_calls: tuple[ToolCallResponse, ...] = ()
    approval_request: ApprovalRequestResponse | None = None


class ApiErrorResponse(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    code: str
    message: str

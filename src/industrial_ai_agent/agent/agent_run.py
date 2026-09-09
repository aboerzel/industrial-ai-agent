import re
from enum import StrEnum
from typing import Annotated, Any, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    ValidationError,
    field_validator,
    model_validator,
)

MAX_TOOL_CALLS = 4
MAX_NEXT_STEPS = 5
MAX_NEXT_STEP_LENGTH = 500
MAX_INVESTIGATION_STEP_FINDING_LENGTH = 1_000
MAX_IDENTIFIER_REFERENCES = 12
MAX_DOCUMENT_REFERENCES = 5
_FORBIDDEN_ACTION_SECTION_TITLES = frozenset(
    {
        "recommended actions",
        "recommended investigation actions",
        "next steps",
        "suggested actions",
        "follow-up actions",
        "empfohlene maßnahmen",
        "empfohlene untersuchungsschritte",
        "nächste schritte",
        "handlungsempfehlungen",
    }
)
_FORBIDDEN_INVESTIGATION_SUMMARY_SECTION_TITLES = frozenset(
    {
        "investigation summary",
        "investigation steps",
        "tool summary",
        "tool calls",
        "untersuchungsschritte",
        "untersuchungsübersicht",
    }
)

NextStep = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True, min_length=1, max_length=MAX_NEXT_STEP_LENGTH
    ),
]

InvestigationStepFinding = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        max_length=MAX_INVESTIGATION_STEP_FINDING_LENGTH,
    ),
]


class UnknownToolError(ValueError):
    pass


class FinalAgentOutputContractError(ValueError):
    """A final response violated the authoritative structured-output contract."""


class InvalidToolArgumentsError(ValueError):
    pass


class ToolCallLimitExceededError(RuntimeError):
    pass


class MissingLLMResponseTextError(RuntimeError):
    pass


class AgentRunStatus(StrEnum):
    SUCCESS = "SUCCESS"
    LIMIT_REACHED = "LIMIT_REACHED"


class IdentifierType(StrEnum):
    """Closed technical-reference types that the UI can handle deterministically."""

    ERROR_CODE = "error_code"
    STATION = "station"
    PRODUCT = "product"
    MAINTENANCE_TICKET = "maintenance_ticket"


class IdentifierReference(BaseModel):
    """A canonical identifier derived from authorized run evidence."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    value: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=2, max_length=64)
    ]
    type: IdentifierType


class DocumentReference(BaseModel):
    """Bounded, non-secret metadata for a document returned by retrieval."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    document_id: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=128)
    ]
    title: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=256)
    ]
    format: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=64)
    ] = "document"


class FinalAgentOutput(BaseModel):
    """Bounded user-facing result emitted after the final model decision."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    answer: Annotated[str, StringConstraints(min_length=1, max_length=8_000)]
    investigation_steps: tuple["InvestigationStep", ...] = Field(
        default=(), max_length=MAX_TOOL_CALLS
    )
    next_steps: tuple[NextStep, ...] = Field(default=(), max_length=MAX_NEXT_STEPS)
    identifiers: tuple[IdentifierReference, ...] = Field(
        default=(), max_length=MAX_IDENTIFIER_REFERENCES
    )
    documents: tuple[DocumentReference, ...] = Field(
        default=(), max_length=MAX_DOCUMENT_REFERENCES
    )

    @classmethod
    def from_model_text(cls, text: str) -> Self:
        """Normalize legacy text without extracting actions from Markdown."""
        try:
            return cls.model_validate_json(text).unwrap_serialized_answer()
        except ValidationError:
            return cls(answer=text)

    def unwrap_serialized_answer(self) -> Self:
        """Unwrap a provider's empty JSON wrapper around the final output once.

        Some OpenAI-compatible local providers serialize the requested final object
        into the outer ``answer`` string while also retaining partial outer fields.
        That string is not narrative Markdown, so accept the inner object only when it
        is itself a complete valid final-output projection. The caller still validates
        the resulting tool trajectory against the system-owned execution record.
        """
        try:
            return type(self).model_validate_json(self.answer)
        except ValidationError:
            return self

    def forbidden_action_sections(self) -> tuple[str, ...]:
        """Return only explicitly forbidden Markdown section titles in the answer."""
        return tuple(
            title
            for line in self.answer.splitlines()
            if (title := _normalize_markdown_heading(line))
            in _FORBIDDEN_ACTION_SECTION_TITLES
        )

    def require_no_action_sections(self) -> None:
        """Keep follow-up prompts exclusively in ``next_steps``."""
        sections = self.forbidden_action_sections()
        if sections:
            raise FinalAgentOutputContractError(
                "Final answer contains a forbidden action section: "
                + ", ".join(sections)
            )

    def forbidden_investigation_summary_sections(self) -> tuple[str, ...]:
        """Return headings that duplicate the structured tool summary."""
        return tuple(
            title
            for line in self.answer.splitlines()
            if (title := _normalize_markdown_heading(line))
            in _FORBIDDEN_INVESTIGATION_SUMMARY_SECTION_TITLES
        )

    def require_no_investigation_summary_sections(self) -> None:
        """Keep executed-tool summaries exclusively in ``investigation_steps``."""
        sections = self.forbidden_investigation_summary_sections()
        if sections:
            raise FinalAgentOutputContractError(
                "Final answer contains a forbidden investigation summary section: "
                + ", ".join(sections)
            )


def _normalize_markdown_heading(line: str) -> str:
    """Normalize a standalone Markdown heading without interpreting list content."""
    normalized = re.sub(r"^#{1,6}\s*", "", line.strip())
    if (
        normalized.startswith("**")
        and normalized.endswith("**")
        or normalized.startswith("__")
        and normalized.endswith("__")
    ):
        normalized = normalized[2:-2]
    return " ".join(normalized.removesuffix(":").split()).casefold()


class ExecutedToolCall(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    tool: str
    arguments: dict[str, Any]

    @field_validator("tool")
    @classmethod
    def validate_tool(cls, tool: str) -> str:
        normalized_tool = tool.strip()
        if not normalized_tool:
            raise ValueError("tool must not be empty")
        return normalized_tool


class InvestigationStep(BaseModel):
    """Bounded public projection of one completed tool observation."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    step: int = Field(ge=1, le=MAX_TOOL_CALLS)
    action: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=1, max_length=128),
    ]
    finding: InvestigationStepFinding

    @model_validator(mode="before")
    @classmethod
    def normalize_legacy_tool_field(cls, value: object) -> object:
        """Accept a documented local-model spelling before trajectory validation.

        The public/API name is always ``action``. Some local structured responses use
        ``tool`` despite the schema; mapping it here does not grant it authority because
        the agent later verifies every action against actual execution.
        """
        if not isinstance(value, dict) or "action" in value or "tool" not in value:
            return value
        normalized = dict(value)
        normalized["action"] = normalized.pop("tool")
        return normalized


class AgentRunResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    status: AgentRunStatus
    final_answer: str | None = None
    investigation_steps: tuple[InvestigationStep, ...] = Field(
        default=(), max_length=MAX_TOOL_CALLS
    )
    next_steps: tuple[NextStep, ...] = Field(default=(), max_length=MAX_NEXT_STEPS)
    identifiers: tuple[IdentifierReference, ...] = Field(
        default=(), max_length=MAX_IDENTIFIER_REFERENCES
    )
    documents: tuple[DocumentReference, ...] = Field(
        default=(), max_length=MAX_DOCUMENT_REFERENCES
    )
    tool_call_count: int = Field(ge=0, le=MAX_TOOL_CALLS)
    executed_tool_calls: tuple[ExecutedToolCall, ...] = ()
    model_profile_name: str | None = None

    @model_validator(mode="after")
    def validate_status_fields(self) -> Self:
        if self.tool_call_count != len(self.executed_tool_calls):
            raise ValueError(
                "tool_call_count must match the number of executed tool calls"
            )
        if self.investigation_steps:
            if len(self.investigation_steps) != self.tool_call_count:
                raise ValueError(
                    "investigation_steps must match completed tool-call count"
                )
            if tuple(step.step for step in self.investigation_steps) != tuple(
                range(1, self.tool_call_count + 1)
            ):
                raise ValueError("investigation_steps must use execution order")
            if tuple(step.action for step in self.investigation_steps) != tuple(
                call.tool for call in self.executed_tool_calls
            ):
                raise ValueError(
                    "investigation_steps actions must match executed tool calls"
                )
        if self.status is AgentRunStatus.SUCCESS and self.final_answer is None:
            raise ValueError("SUCCESS requires a final answer")
        if self.status is AgentRunStatus.LIMIT_REACHED:
            if self.final_answer is not None:
                raise ValueError("LIMIT_REACHED cannot contain a final answer")
            if self.next_steps:
                raise ValueError("LIMIT_REACHED cannot contain next steps")
            if self.identifiers:
                raise ValueError("LIMIT_REACHED cannot contain identifiers")
            if self.documents:
                raise ValueError("LIMIT_REACHED cannot contain documents")
            if self.investigation_steps:
                raise ValueError("LIMIT_REACHED cannot contain investigation steps")
            if self.tool_call_count != MAX_TOOL_CALLS:
                raise ValueError(
                    f"LIMIT_REACHED requires {MAX_TOOL_CALLS} executed tool calls"
                )
        return self

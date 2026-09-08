"""Application service for one routed, MCP-backed troubleshooting run."""

from contextlib import AbstractAsyncContextManager, AbstractContextManager
from dataclasses import dataclass
from typing import Literal, Protocol
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from industrial_ai_agent.agent.agent_run import (
    AgentRunResult,
    InvalidToolArgumentsError,
)
from industrial_ai_agent.agent.llm import ModelProfile
from industrial_ai_agent.agent.model_egress import DataClassification
from industrial_ai_agent.agent.model_routing import (
    DeterministicModelRouter,
    ModelProfileMetadata,
    TaskRequirements,
)
from industrial_ai_agent.agent.response_language import (
    ResponseLanguage,
    detect_response_language,
)
from industrial_ai_agent.agent.run_classification_policy import (
    AgentRunClassificationPolicy,
    AgentRunProfile,
    InternalDiagnosticTarget,
    ResolvedRunPolicy,
)


class McpServiceUnavailableError(RuntimeError):
    """Raised when an MCP service cannot be reached for an agent run."""


class InternalDiagnosticTargetUnavailableError(RuntimeError):
    """Raised without revealing whether an unavailable target is higher classified."""


class AgentRunService(Protocol):
    """Application boundary used by external clients to start troubleshooting runs."""

    async def run(self, message: str) -> AgentRunResult: ...

    async def resolve_internal_diagnostic(
        self, target: InternalDiagnosticTarget
    ) -> ResolvedRunPolicy: ...

    async def run_with_policy(
        self,
        message: str,
        *,
        run_policy: ResolvedRunPolicy,
        response_language: ResponseLanguage | None = None,
    ) -> AgentRunResult: ...


class InternalDiagnosticScopeValidator(Protocol):
    """Verify target visibility through a profile-bounded data access path."""

    async def is_available(self, target: InternalDiagnosticTarget) -> bool: ...


class PendingApproval(BaseModel):
    """Strict application contract between a LangGraph interrupt and FastAPI."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    action: Literal["create_maintenance_ticket"]
    arguments: dict[str, str]
    summary: str = Field(min_length=1, max_length=500)


@dataclass(frozen=True, slots=True)
class ConversationTurn:
    """Prior visible user/agent exchange, never an authorization input."""

    user_request: str
    agent_answer: str | None


@dataclass(frozen=True, slots=True)
class RunExecution:
    result: AgentRunResult | None = None
    approval: PendingApproval | None = None

    def __post_init__(self) -> None:
        if (self.result is None) == (self.approval is None):
            raise ValueError("Run execution must be final or waiting for approval")


class McpBackedTroubleshootingAgent(Protocol):
    """The narrow LangGraph operation needed by the application service."""

    async def aanswer_via_mcp(
        self,
        user_request: str,
        *,
        response_language: ResponseLanguage | None = None,
        conversation_context: tuple[ConversationTurn, ...] = (),
    ) -> AgentRunResult: ...

    async def astart_via_mcp(
        self,
        user_request: str,
        *,
        thread_id: str,
        response_language: ResponseLanguage | None = None,
        conversation_context: tuple[ConversationTurn, ...] = (),
    ) -> tuple[object, dict[str, object] | None]: ...

    async def aresume_via_mcp(self, *, thread_id: str, approval: object) -> object: ...


class RoutedTroubleshootingAgentFactory(Protocol):
    """Owns provider and MCP composition for one already-routed agent run."""

    def open_agent(
        self,
        *,
        profile: ModelProfile,
        run_policy: ResolvedRunPolicy,
        checkpointer: object | None = None,
    ) -> AbstractContextManager[McpBackedTroubleshootingAgent]: ...


class RuntimeCheckpointerFactory(Protocol):
    def open(self) -> AbstractAsyncContextManager[object]: ...


class TroubleshootingRunService:
    """Run confidential troubleshooting through routed LangGraph and MCP dependencies."""

    def __init__(
        self,
        *,
        router: DeterministicModelRouter,
        profiles: tuple[ModelProfileMetadata, ...],
        agent_factory: RoutedTroubleshootingAgentFactory,
        checkpointer_factory: RuntimeCheckpointerFactory | None = None,
        classification_policy: AgentRunClassificationPolicy | None = None,
        internal_diagnostic_scope_validator: InternalDiagnosticScopeValidator
        | None = None,
    ) -> None:
        self._router = router
        self._profiles = profiles
        self._agent_factory = agent_factory
        self._checkpointer_factory = checkpointer_factory
        self._classification_policy = (
            classification_policy or AgentRunClassificationPolicy()
        )
        self._internal_diagnostic_scope_validator = internal_diagnostic_scope_validator

    @property
    def persistent_hitl_enabled(self) -> bool:
        return self._checkpointer_factory is not None

    async def run(self, message: str) -> AgentRunResult:
        return await self.run_with_policy(
            message,
            run_policy=self._classification_policy.resolve(
                AgentRunProfile.CONFIDENTIAL_TROUBLESHOOTING
            ),
            response_language=detect_response_language(message),
        )

    async def run_with_policy(
        self,
        message: str,
        *,
        run_policy: ResolvedRunPolicy,
        response_language: ResponseLanguage | None = None,
        conversation_context: tuple[ConversationTurn, ...] = (),
    ) -> AgentRunResult:
        profile = self._router.route(run_policy.task_requirements, self._profiles)
        resolved_response_language = response_language or detect_response_language(
            message
        )
        try:
            with self._agent_factory.open_agent(
                profile=profile,
                run_policy=run_policy,
            ) as agent:
                if not conversation_context:
                    return await agent.aanswer_via_mcp(
                        message, response_language=resolved_response_language
                    )
                return await agent.aanswer_via_mcp(
                    message,
                    response_language=resolved_response_language,
                    conversation_context=conversation_context,
                )
        except BaseExceptionGroup as error:
            root_cause = _single_exception_group_cause(error)
            if isinstance(root_cause, McpServiceUnavailableError):
                raise McpServiceUnavailableError(
                    "MCP service is unavailable"
                ) from error
            if isinstance(root_cause, InvalidToolArgumentsError):
                raise root_cause from error
            raise

    async def resolve_internal_diagnostic(
        self, target: InternalDiagnosticTarget
    ) -> ResolvedRunPolicy:
        validator = self._internal_diagnostic_scope_validator
        if validator is None or not await validator.is_available(target):
            raise InternalDiagnosticTargetUnavailableError(
                "Internal diagnostic target is unavailable"
            )
        return self._classification_policy.resolve(AgentRunProfile.INTERNAL_DIAGNOSTIC)

    async def start(
        self,
        message: str,
        *,
        run_id: UUID,
        run_policy: ResolvedRunPolicy | None = None,
        response_language: ResponseLanguage | None = None,
        conversation_context: tuple[ConversationTurn, ...] = (),
    ) -> tuple[ModelProfile, RunExecution]:
        if self._checkpointer_factory is None:
            raise RuntimeError("Persistent HITL runs require a PostgreSQL checkpointer")
        resolved = run_policy or self._classification_policy.resolve(
            AgentRunProfile.CONFIDENTIAL_TROUBLESHOOTING
        )
        profile = self._router.route(resolved.task_requirements, self._profiles)
        resolved_response_language = response_language or detect_response_language(
            message
        )
        async with self._checkpointer_factory.open() as saver:
            with self._agent_factory.open_agent(
                profile=profile, run_policy=resolved, checkpointer=saver
            ) as agent:
                state, payload = await agent.astart_via_mcp(
                    message,
                    thread_id=str(run_id),
                    response_language=resolved_response_language,
                    conversation_context=conversation_context,
                )
        return profile, _execution_from_state(state, payload)

    async def resume(
        self,
        *,
        run_id: UUID,
        model_profile: str,
        data_classification: DataClassification,
        run_profile: AgentRunProfile,
        decision: str,
    ) -> RunExecution:
        if self._checkpointer_factory is None:
            raise RuntimeError("Persistent HITL runs require a PostgreSQL checkpointer")
        resolved = self._classification_policy.resolve_persisted(
            profile=run_profile, data_classification=data_classification
        )
        profile = ModelProfile(model_profile)
        if profile not in {metadata.profile for metadata in self._profiles}:
            raise RuntimeError("Persisted run model profile is not configured")
        async with self._checkpointer_factory.open() as saver:
            with self._agent_factory.open_agent(
                profile=profile, run_policy=resolved, checkpointer=saver
            ) as agent:
                state = await agent.aresume_via_mcp(
                    thread_id=str(run_id), approval=decision
                )
        return _execution_from_state(state, None)


def confidential_troubleshooting_requirements() -> TaskRequirements:
    """Build the conservative, server-controlled requirements for this API use case."""
    return (
        AgentRunClassificationPolicy()
        .resolve(AgentRunProfile.CONFIDENTIAL_TROUBLESHOOTING)
        .task_requirements
    )


def internal_diagnostic_message(target: InternalDiagnosticTarget) -> str:
    """Construct the only prompt form accepted by the structured diagnostic path."""
    return (
        "Perform a read-only internal diagnostic for product "
        f"{target.product_id} at station {target.station_id}. "
        "Use only available internal evidence and report when evidence is unavailable."
    )


def _single_exception_group_cause(error: BaseExceptionGroup) -> BaseException:
    """Expose one nested cause without discarding multi-cause failure context."""
    cause: BaseException = error
    while isinstance(cause, BaseExceptionGroup) and len(cause.exceptions) == 1:
        cause = cause.exceptions[0]
    return cause


def _execution_from_state(
    state: object, payload: dict[str, object] | None
) -> RunExecution:
    values = state  # TypedDict remains deliberately hidden behind the application port.
    if not isinstance(values, dict):
        raise TypeError("LangGraph returned an invalid state")
    run_status = values.get("run_status")
    if payload is not None:
        details = payload.get("details")
        if not isinstance(details, dict) or not isinstance(payload.get("action"), str):
            raise RuntimeError("LangGraph returned an invalid approval payload")
        arguments = {str(key): str(value) for key, value in details.items()}
        summary = arguments.get("summary", "Approval required.")
        return RunExecution(
            approval=PendingApproval(
                action=payload["action"], arguments=arguments, summary=summary
            )
        )
    if run_status is None:
        raise RuntimeError("LangGraph run neither completed nor interrupted")
    return RunExecution(
        result=AgentRunResult(
            status=run_status,
            final_answer=values.get("final_answer"),
            tool_call_count=values.get("executed_tool_count", 0),
            executed_tool_calls=values.get("executed_tool_calls", ()),
            model_profile_name=values.get("model_profile_name"),
        )
    )

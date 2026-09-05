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
    CostPreference,
    DeterministicModelRouter,
    LLMCapability,
    ModelProfileMetadata,
    QualityClass,
    TaskRequirements,
    TaskRole,
)


class McpServiceUnavailableError(RuntimeError):
    """Raised when an MCP service cannot be reached for an agent run."""


class AgentRunService(Protocol):
    """Application boundary used by external clients to start troubleshooting runs."""

    async def run(self, message: str) -> AgentRunResult: ...


class PendingApproval(BaseModel):
    """Strict application contract between a LangGraph interrupt and FastAPI."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    action: Literal["create_maintenance_ticket"]
    arguments: dict[str, str]
    summary: str = Field(min_length=1, max_length=500)


@dataclass(frozen=True, slots=True)
class RunExecution:
    result: AgentRunResult | None = None
    approval: PendingApproval | None = None

    def __post_init__(self) -> None:
        if (self.result is None) == (self.approval is None):
            raise ValueError("Run execution must be final or waiting for approval")


class McpBackedTroubleshootingAgent(Protocol):
    """The narrow LangGraph operation needed by the application service."""

    async def aanswer_via_mcp(self, user_request: str) -> AgentRunResult: ...

    async def astart_via_mcp(
        self, user_request: str, *, thread_id: str
    ) -> tuple[object, dict[str, object] | None]: ...

    async def aresume_via_mcp(self, *, thread_id: str, approval: object) -> object: ...


class RoutedTroubleshootingAgentFactory(Protocol):
    """Owns provider and MCP composition for one already-routed agent run."""

    def open_agent(
        self,
        *,
        profile: ModelProfile,
        requirements: TaskRequirements,
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
    ) -> None:
        self._router = router
        self._profiles = profiles
        self._agent_factory = agent_factory
        self._checkpointer_factory = checkpointer_factory

    @property
    def persistent_hitl_enabled(self) -> bool:
        return self._checkpointer_factory is not None

    async def run(self, message: str) -> AgentRunResult:
        requirements = confidential_troubleshooting_requirements()
        profile = self._router.route(requirements, self._profiles)
        try:
            with self._agent_factory.open_agent(
                profile=profile,
                requirements=requirements,
            ) as agent:
                return await agent.aanswer_via_mcp(message)
        except BaseExceptionGroup as error:
            root_cause = _single_exception_group_cause(error)
            if isinstance(root_cause, McpServiceUnavailableError):
                raise McpServiceUnavailableError(
                    "MCP service is unavailable"
                ) from error
            if isinstance(root_cause, InvalidToolArgumentsError):
                raise root_cause from error
            raise

    async def start(
        self, message: str, *, run_id: UUID
    ) -> tuple[ModelProfile, RunExecution]:
        if self._checkpointer_factory is None:
            raise RuntimeError("Persistent HITL runs require a PostgreSQL checkpointer")
        requirements = confidential_troubleshooting_requirements()
        profile = self._router.route(requirements, self._profiles)
        async with self._checkpointer_factory.open() as saver:
            with self._agent_factory.open_agent(
                profile=profile, requirements=requirements, checkpointer=saver
            ) as agent:
                state, payload = await agent.astart_via_mcp(
                    message, thread_id=str(run_id)
                )
        return profile, _execution_from_state(state, payload)

    async def resume(
        self,
        *,
        run_id: UUID,
        model_profile: str,
        data_classification: DataClassification,
        decision: str,
    ) -> RunExecution:
        if self._checkpointer_factory is None:
            raise RuntimeError("Persistent HITL runs require a PostgreSQL checkpointer")
        requirements = confidential_troubleshooting_requirements()
        if requirements.data_classification is not data_classification:
            raise RuntimeError(
                "Persisted run data classification does not match the use case"
            )
        profile = ModelProfile(model_profile)
        if profile not in {metadata.profile for metadata in self._profiles}:
            raise RuntimeError("Persisted run model profile is not configured")
        async with self._checkpointer_factory.open() as saver:
            with self._agent_factory.open_agent(
                profile=profile, requirements=requirements, checkpointer=saver
            ) as agent:
                state = await agent.aresume_via_mcp(
                    thread_id=str(run_id), approval=decision
                )
        return _execution_from_state(state, None)


def confidential_troubleshooting_requirements() -> TaskRequirements:
    """Build the conservative, server-controlled requirements for this API use case."""
    return TaskRequirements(
        task_role=TaskRole.TROUBLESHOOTING,
        required_capabilities=frozenset(
            {LLMCapability.TEXT, LLMCapability.TOOL_CALLING}
        ),
        minimum_quality=QualityClass.HIGH,
        cost_preference=CostPreference.PREFER_QUALITY,
        data_classification=DataClassification.CONFIDENTIAL,
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

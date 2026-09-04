"""Application service for one routed, MCP-backed troubleshooting run."""

from contextlib import AbstractContextManager
from typing import Protocol

from industrial_ai_agent.agent.agent_run import AgentRunResult
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


class McpBackedTroubleshootingAgent(Protocol):
    """The narrow LangGraph operation needed by the application service."""

    async def aanswer_via_mcp(self, user_request: str) -> AgentRunResult: ...


class RoutedTroubleshootingAgentFactory(Protocol):
    """Owns provider and MCP composition for one already-routed agent run."""

    def open_agent(
        self,
        *,
        profile: ModelProfile,
        requirements: TaskRequirements,
    ) -> AbstractContextManager[McpBackedTroubleshootingAgent]: ...


class TroubleshootingRunService:
    """Run confidential troubleshooting through routed LangGraph and MCP dependencies."""

    def __init__(
        self,
        *,
        router: DeterministicModelRouter,
        profiles: tuple[ModelProfileMetadata, ...],
        agent_factory: RoutedTroubleshootingAgentFactory,
    ) -> None:
        self._router = router
        self._profiles = profiles
        self._agent_factory = agent_factory

    async def run(self, message: str) -> AgentRunResult:
        requirements = confidential_troubleshooting_requirements()
        profile = self._router.route(requirements, self._profiles)
        try:
            with self._agent_factory.open_agent(
                profile=profile,
                requirements=requirements,
            ) as agent:
                return await agent.aanswer_via_mcp(message)
        except* McpServiceUnavailableError as error:
            # Streamable HTTP task groups can nest the underlying transport failure.
            raise McpServiceUnavailableError("MCP service is unavailable") from error


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

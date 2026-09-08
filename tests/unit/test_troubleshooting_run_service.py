import asyncio
from collections.abc import Iterator
from contextlib import AbstractContextManager, contextmanager

import pytest

from industrial_ai_agent.agent.agent_run import (
    AgentRunResult,
    AgentRunStatus,
    InvalidToolArgumentsError,
)
from industrial_ai_agent.agent.llm import ModelProfile
from industrial_ai_agent.agent.model_egress import DataClassification, ExecutionZone
from industrial_ai_agent.agent.model_routing import (
    CostClass,
    DeterministicModelRouter,
    LLMCapability,
    ModelProfileMetadata,
    QualityClass,
)
from industrial_ai_agent.agent.response_language import ResponseLanguage
from industrial_ai_agent.agent.run_classification_policy import ResolvedRunPolicy
from industrial_ai_agent.agent.troubleshooting_run_service import (
    McpBackedTroubleshootingAgent,
    RoutedTroubleshootingAgentFactory,
    TroubleshootingRunService,
)


class FakeAgent:
    @staticmethod
    async def aanswer_via_mcp(
        user_request: str, *, response_language: ResponseLanguage | None = None
    ) -> AgentRunResult:
        assert user_request == "Investigate P4711."
        assert response_language is ResponseLanguage.EN
        return AgentRunResult(
            status=AgentRunStatus.SUCCESS,
            final_answer="Diagnosis complete.",
            tool_call_count=0,
        )


class CapturingFactory(RoutedTroubleshootingAgentFactory):
    def __init__(self) -> None:
        self.profile: ModelProfile | None = None
        self.classification: DataClassification | None = None
        self.run_policy: ResolvedRunPolicy | None = None

    def open_agent(
        self,
        *,
        profile: ModelProfile,
        run_policy: ResolvedRunPolicy,
    ) -> AbstractContextManager[McpBackedTroubleshootingAgent]:
        return self._open_agent(profile=profile, run_policy=run_policy)

    @contextmanager
    def _open_agent(
        self,
        *,
        profile: ModelProfile,
        run_policy: ResolvedRunPolicy,
    ) -> Iterator[McpBackedTroubleshootingAgent]:
        self.profile = profile
        self.classification = run_policy.data_classification
        self.run_policy = run_policy
        yield FakeAgent()


class FailingAgent:
    @staticmethod
    async def aanswer_via_mcp(
        user_request: str, *, response_language: ResponseLanguage | None = None
    ) -> AgentRunResult:
        assert user_request == "Investigate P4711."
        assert response_language is ResponseLanguage.EN
        raise ExceptionGroup(
            "nested MCP shutdown failure",
            [
                ExceptionGroup(
                    "session failure",
                    [
                        InvalidToolArgumentsError(
                            "Invalid arguments for get_product_history"
                        )
                    ],
                )
            ],
        )


class FailingFactory(CapturingFactory):
    @contextmanager
    def _open_agent(
        self,
        *,
        profile: ModelProfile,
        run_policy: ResolvedRunPolicy,
    ) -> Iterator[McpBackedTroubleshootingAgent]:
        self.profile = profile
        self.classification = run_policy.data_classification
        self.run_policy = run_policy
        yield FailingAgent()


def test_troubleshooting_run_service_routes_confidential_requests_server_side() -> None:
    selected_profile = ModelProfile("local_quality")
    factory = CapturingFactory()
    service = TroubleshootingRunService(
        router=DeterministicModelRouter(),
        profiles=(
            ModelProfileMetadata(
                profile=selected_profile,
                capabilities=frozenset(
                    {LLMCapability.TEXT, LLMCapability.TOOL_CALLING}
                ),
                quality_class=QualityClass.HIGH,
                cost_class=CostClass.HIGH,
                execution_zone=ExecutionZone.LOCAL,
                max_data_classification=DataClassification.RESTRICTED,
            ),
        ),
        agent_factory=factory,
    )

    result = asyncio.run(service.run("Investigate P4711."))

    assert result.status is AgentRunStatus.SUCCESS
    assert factory.profile == selected_profile
    assert factory.classification is DataClassification.CONFIDENTIAL


def test_single_cause_exception_group_preserves_invalid_tool_arguments_error() -> None:
    selected_profile = ModelProfile("local_quality")
    service = TroubleshootingRunService(
        router=DeterministicModelRouter(),
        profiles=(
            ModelProfileMetadata(
                profile=selected_profile,
                capabilities=frozenset(
                    {LLMCapability.TEXT, LLMCapability.TOOL_CALLING}
                ),
                quality_class=QualityClass.HIGH,
                cost_class=CostClass.HIGH,
                execution_zone=ExecutionZone.LOCAL,
                max_data_classification=DataClassification.RESTRICTED,
            ),
        ),
        agent_factory=FailingFactory(),
    )

    with pytest.raises(InvalidToolArgumentsError, match="get_product_history"):
        asyncio.run(service.run("Investigate P4711."))

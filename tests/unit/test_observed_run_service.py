import asyncio
from uuid import uuid4

from industrial_ai_agent.agent.agent_run import AgentRunResult, AgentRunStatus
from industrial_ai_agent.agent.llm import ModelProfile
from industrial_ai_agent.agent.response_language import ResponseLanguage
from industrial_ai_agent.agent.run_classification_policy import (
    AgentRunClassificationPolicy,
    AgentRunProfile,
)
from industrial_ai_agent.agent.troubleshooting_run_service import (
    ConversationTurn,
    RunExecution,
)
from industrial_ai_agent.infrastructure.observed_run_service import (
    ObservedTroubleshootingRunService,
)
from industrial_ai_agent.infrastructure.telemetry import Telemetry, TelemetryConfiguration


class RecordingPersistentRunService:
    persistent_hitl_enabled = True

    def __init__(self) -> None:
        self.start_contexts: list[tuple[ConversationTurn, ...]] = []
        self.run_contexts: list[tuple[ConversationTurn, ...]] = []

    async def start(
        self,
        message: str,
        *,
        run_id,
        run_policy,
        response_language: ResponseLanguage | None = None,
        conversation_context: tuple[ConversationTurn, ...] = (),
    ) -> tuple[ModelProfile, RunExecution]:
        del message, run_id, run_policy, response_language
        self.start_contexts.append(conversation_context)
        return _profile(), RunExecution(result=_success_result())

    async def run_with_policy(
        self,
        message: str,
        *,
        run_policy,
        response_language: ResponseLanguage | None = None,
        conversation_context: tuple[ConversationTurn, ...] = (),
    ) -> AgentRunResult:
        del message, run_policy, response_language
        self.run_contexts.append(conversation_context)
        return _success_result()


def test_observed_service_starts_first_persistent_investigation_without_history() -> None:
    delegate = RecordingPersistentRunService()
    service = ObservedTroubleshootingRunService(delegate, _disabled_telemetry())
    policy = AgentRunClassificationPolicy().resolve(
        AgentRunProfile.CONFIDENTIAL_TROUBLESHOOTING
    )

    profile, execution = asyncio.run(
        service.start(
            "Investigate product P4711 at station S04.",
            run_id=uuid4(),
            run_policy=policy,
            response_language=ResponseLanguage.EN,
            conversation_context=(),
        )
    )

    assert profile == _profile()
    assert execution.result == _success_result()
    assert delegate.start_contexts == [()]


def test_observed_service_forwards_bounded_follow_up_context() -> None:
    delegate = RecordingPersistentRunService()
    service = ObservedTroubleshootingRunService(delegate, _disabled_telemetry())
    policy = AgentRunClassificationPolicy().resolve(
        AgentRunProfile.CONFIDENTIAL_TROUBLESHOOTING
    )
    context = (
        ConversationTurn(
            user_request="Investigate product P4711 at station S04.",
            agent_answer="1. Inspect the station status.",
        ),
    )

    result = asyncio.run(
        service.run_with_policy(
            "Check the first recommended action in more detail.",
            run_policy=policy,
            response_language=ResponseLanguage.EN,
            conversation_context=context,
        )
    )

    assert result == _success_result()
    assert delegate.run_contexts == [context]


def _disabled_telemetry() -> Telemetry:
    return Telemetry(TelemetryConfiguration(enabled=False))


def _profile() -> ModelProfile:
    return ModelProfile("local_quality")


def _success_result() -> AgentRunResult:
    return AgentRunResult(
        status=AgentRunStatus.SUCCESS,
        final_answer="Completed.",
        tool_call_count=0,
    )

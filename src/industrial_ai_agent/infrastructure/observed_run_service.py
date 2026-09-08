"""Infrastructure decorator that correlates agent runs without changing Core ports."""

from time import perf_counter
from uuid import UUID

from industrial_ai_agent.agent.agent_run import AgentRunResult
from industrial_ai_agent.agent.llm import ModelProfile
from industrial_ai_agent.agent.model_egress import DataClassification
from industrial_ai_agent.agent.response_language import ResponseLanguage
from industrial_ai_agent.agent.run_classification_policy import (
    AgentRunClassificationPolicy,
    AgentRunProfile,
    InternalDiagnosticTarget,
    ResolvedRunPolicy,
)
from industrial_ai_agent.agent.troubleshooting_run_service import (
    AgentRunService,
    ConversationTurn,
    RunExecution,
    TroubleshootingRunService,
)
from industrial_ai_agent.infrastructure.telemetry import Telemetry, sanitized_error_code


class ObservedTroubleshootingRunService:
    """Trace application operations at the infrastructure composition boundary."""

    def __init__(
        self, delegate: TroubleshootingRunService, telemetry: Telemetry
    ) -> None:
        self._delegate = delegate
        self._telemetry = telemetry

    @property
    def persistent_hitl_enabled(self) -> bool:
        return self._delegate.persistent_hitl_enabled

    async def run(self, message: str) -> AgentRunResult:
        return await self._observe_run(
            run_id=None,
            operation=self._delegate.run,
            message=message,
            run_policy=AgentRunClassificationPolicy().resolve(
                AgentRunProfile.CONFIDENTIAL_TROUBLESHOOTING
            ),
        )

    async def resolve_internal_diagnostic(
        self, target: InternalDiagnosticTarget
    ) -> ResolvedRunPolicy:
        return await self._delegate.resolve_internal_diagnostic(target)

    async def run_with_policy(
        self,
        message: str,
        *,
        run_policy: ResolvedRunPolicy,
        response_language: ResponseLanguage | None = None,
        conversation_context: tuple[ConversationTurn, ...] = (),
    ) -> AgentRunResult:
        async def operation(value: str) -> AgentRunResult:
            if conversation_context:
                return await self._delegate.run_with_policy(
                    value,
                    run_policy=run_policy,
                    response_language=response_language,
                    conversation_context=conversation_context,
                )
            return await self._delegate.run_with_policy(
                value,
                run_policy=run_policy,
                response_language=response_language,
            )

        return await self._observe_run(
            run_id=None,
            operation=operation,
            message=message,
            run_policy=run_policy,
            response_language=response_language,
        )

    async def start(
        self,
        message: str,
        *,
        run_id: UUID,
        run_policy: ResolvedRunPolicy,
        response_language: ResponseLanguage | None = None,
        conversation_context: tuple[ConversationTurn, ...] = (),
    ) -> tuple[ModelProfile, RunExecution]:
        return await self._observe_run(
            run_id=run_id,
            operation=self._delegate.start,
            message=message,
            run_policy=run_policy,
            response_language=response_language,
            conversation_context=conversation_context,
        )

    async def resume(
        self,
        *,
        run_id: UUID,
        model_profile: str,
        data_classification: DataClassification,
        run_profile: AgentRunProfile,
        decision: str,
    ) -> RunExecution:
        attributes = {
            "run.id": str(run_id),
            "data.classification": data_classification.name,
            "run.profile": run_profile.value,
            "approval.decision": decision,
        }
        self._telemetry.record_approval(
            decision=decision, classification=data_classification.name
        )
        with self._telemetry.span("approval.resume", attributes):
            return await self._delegate.resume(
                run_id=run_id,
                model_profile=model_profile,
                data_classification=data_classification,
                run_profile=run_profile,
                decision=decision,
            )

    async def _observe_run(
        self,
        *,
        run_id: UUID | None,
        operation,
        message: str,
        run_policy: ResolvedRunPolicy,
        response_language: ResponseLanguage | None = None,
        conversation_context: tuple[ConversationTurn, ...] = (),
    ):
        attributes: dict[str, object] = {
            "data.classification": run_policy.data_classification.name,
            "run.profile": run_policy.run_profile.value,
        }
        if response_language is not None:
            attributes["response.language"] = response_language.value.lower()
        if run_id is not None:
            attributes["run.id"] = str(run_id)
        started = perf_counter()
        status = "success"
        try:
            with (
                self._telemetry.span("agent.run", attributes),
                self._telemetry.span("model.routing", attributes),
            ):
                if run_id is None:
                    result = await operation(message)
                elif conversation_context:
                    result = await operation(
                        message,
                        run_id=run_id,
                        run_policy=run_policy,
                        response_language=response_language,
                        conversation_context=conversation_context,
                    )
                else:
                    result = await operation(
                        message,
                        run_id=run_id,
                        run_policy=run_policy,
                        response_language=response_language,
                    )
            self._telemetry.log_event(
                event="agent.run.completed",
                run_id=str(run_id) if run_id is not None else None,
            )
            return result
        except Exception as error:
            status = "failure"
            self._telemetry.log_error(
                event="agent.run.failed",
                run_id=str(run_id) if run_id is not None else None,
                error_code=sanitized_error_code(error),
            )
            raise
        finally:
            self._telemetry.record_agent_run(
                status=status,
                duration_seconds=perf_counter() - started,
                classification=run_policy.data_classification.name,
            )


def observed_run_service(
    service: TroubleshootingRunService, telemetry: Telemetry
) -> AgentRunService:
    """Expose only the existing application service protocol to FastAPI."""
    return ObservedTroubleshootingRunService(service, telemetry)

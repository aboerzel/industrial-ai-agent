"""Infrastructure decorator that correlates agent runs without changing Core ports."""

from time import perf_counter
from uuid import UUID

from industrial_ai_agent.agent.agent_run import AgentRunResult
from industrial_ai_agent.agent.llm import ModelProfile
from industrial_ai_agent.agent.model_egress import DataClassification
from industrial_ai_agent.agent.troubleshooting_run_service import (
    AgentRunService,
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
            run_id=None, operation=self._delegate.run, message=message
        )

    async def start(
        self, message: str, *, run_id: UUID
    ) -> tuple[ModelProfile, RunExecution]:
        return await self._observe_run(
            run_id=run_id, operation=self._delegate.start, message=message
        )

    async def resume(
        self,
        *,
        run_id: UUID,
        model_profile: str,
        data_classification: DataClassification,
        decision: str,
    ) -> RunExecution:
        attributes = {
            "run.id": str(run_id),
            "data.classification": data_classification.name,
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
                decision=decision,
            )

    async def _observe_run(self, *, run_id: UUID | None, operation, message: str):
        attributes: dict[str, object] = {"data.classification": "CONFIDENTIAL"}
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
                else:
                    result = await operation(message, run_id=run_id)
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
                classification="CONFIDENTIAL",
            )


def observed_run_service(
    service: TroubleshootingRunService, telemetry: Telemetry
) -> AgentRunService:
    """Expose only the existing application service protocol to FastAPI."""
    return ObservedTroubleshootingRunService(service, telemetry)

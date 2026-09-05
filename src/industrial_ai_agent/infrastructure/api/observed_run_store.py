"""Safe persistence-boundary tracing for the API's durable run store."""

from collections.abc import Awaitable, Callable
from time import perf_counter
from typing import ParamSpec, TypeVar
from uuid import UUID

from industrial_ai_agent.agent.agent_run import AgentRunResult
from industrial_ai_agent.agent.run_classification_policy import AgentRunProfile
from industrial_ai_agent.domain.security import DataClassification
from industrial_ai_agent.infrastructure.api.run_store import (
    AgentRunStore,
    StoredAgentRun,
)
from industrial_ai_agent.infrastructure.telemetry import Telemetry

T = TypeVar("T")
P = ParamSpec("P")


class ObservedAgentRunStore:
    """Decorate the existing store without exposing request or result payloads."""

    def __init__(self, delegate: AgentRunStore, telemetry: Telemetry) -> None:
        self._delegate = delegate
        self._telemetry = telemetry

    async def create(self, run_id: UUID, **kwargs: object) -> StoredAgentRun:
        return await self._observe(
            "create", run_id, self._delegate.create, run_id, **kwargs
        )

    async def complete(self, run_id: UUID, result: AgentRunResult) -> StoredAgentRun:
        return await self._observe(
            "complete", run_id, self._delegate.complete, run_id, result
        )

    async def fail(self, run_id: UUID, error_code: str) -> StoredAgentRun:
        return await self._observe(
            "fail", run_id, self._delegate.fail, run_id, error_code
        )

    async def bind_execution_context(
        self,
        run_id: UUID,
        *,
        data_classification: DataClassification,
        run_profile: AgentRunProfile,
        model_profile: str,
    ) -> StoredAgentRun:
        return await self._observe(
            "bind_execution_context",
            run_id,
            self._delegate.bind_execution_context,
            run_id,
            data_classification=data_classification,
            run_profile=run_profile,
            model_profile=model_profile,
        )

    async def get(self, run_id: UUID) -> StoredAgentRun | None:
        return await self._observe("get", run_id, self._delegate.get, run_id)

    async def wait_for_approval(
        self, run_id: UUID, approval_request: dict[str, object]
    ) -> StoredAgentRun:
        return await self._observe(
            "wait_for_approval",
            run_id,
            self._delegate.wait_for_approval,
            run_id,
            approval_request,
        )

    async def claim_resume(
        self, run_id: UUID, *, decision: str
    ) -> StoredAgentRun | None:
        return await self._observe(
            "claim_resume",
            run_id,
            self._delegate.claim_resume,
            run_id,
            decision=decision,
        )

    async def _observe(
        self,
        operation: str,
        run_id: UUID,
        call: Callable[P, Awaitable[T]],
        *args: P.args,
        **kwargs: P.kwargs,
    ) -> T:
        attributes: dict[str, object] = {
            "run.id": str(run_id),
            "persistence.operation": operation,
        }
        started = perf_counter()
        status = "success"
        try:
            with self._telemetry.span("persistence.run_store", attributes) as span:
                result = await call(*args, **kwargs)
                if isinstance(result, StoredAgentRun):
                    attributes.update(
                        {
                            "data.classification": result.data_classification.name,
                            "run.profile": result.run_profile.value,
                        }
                    )
                    self._telemetry.set_span_attributes(span, attributes)
                return result
        except Exception:
            status = "failure"
            raise
        finally:
            self._telemetry.record_persistence_operation(
                attributes={**attributes, "operation.status": status},
                duration_seconds=perf_counter() - started,
            )

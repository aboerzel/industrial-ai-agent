"""Application-facing lifecycle port for durable agent runs."""

import asyncio
from dataclasses import dataclass, replace
from typing import Protocol
from uuid import UUID

from industrial_ai_agent.agent.agent_run import AgentRunResult
from industrial_ai_agent.domain.security import DataClassification
from industrial_ai_agent.infrastructure.api.schemas import RunStatus


@dataclass(frozen=True, slots=True)
class StoredAgentRun:
    run_id: UUID
    thread_id: UUID
    status: RunStatus
    data_classification: DataClassification
    model_profile: str | None = None
    request_text: str = ""
    result: AgentRunResult | None = None
    error_code: str | None = None
    approval_request: dict[str, object] | None = None


class AgentRunStore(Protocol):
    """Persistence boundary for API run lifecycle records."""

    async def create(
        self,
        run_id: UUID,
        *,
        request_text: str = "",
        data_classification: DataClassification = DataClassification.CONFIDENTIAL,
        model_profile: str | None = None,
    ) -> StoredAgentRun: ...

    async def complete(
        self, run_id: UUID, result: AgentRunResult
    ) -> StoredAgentRun: ...

    async def fail(self, run_id: UUID, error_code: str) -> StoredAgentRun: ...

    async def bind_execution_context(
        self,
        run_id: UUID,
        *,
        data_classification: DataClassification,
        model_profile: str,
    ) -> StoredAgentRun: ...

    async def get(self, run_id: UUID) -> StoredAgentRun | None: ...

    async def wait_for_approval(
        self, run_id: UUID, approval_request: dict[str, object]
    ) -> StoredAgentRun: ...

    async def claim_resume(self, run_id: UUID) -> StoredAgentRun | None: ...


class InMemoryAgentRunStore:
    """Development/demo-only store; records vanish when the API process stops."""

    def __init__(self) -> None:
        self._records: dict[UUID, StoredAgentRun] = {}
        self._lock = asyncio.Lock()

    async def create(
        self,
        run_id: UUID,
        *,
        request_text: str = "",
        data_classification: DataClassification = DataClassification.CONFIDENTIAL,
        model_profile: str | None = None,
    ) -> StoredAgentRun:
        record = StoredAgentRun(
            run_id=run_id,
            thread_id=run_id,
            status=RunStatus.RUNNING,
            data_classification=data_classification,
            model_profile=model_profile,
            request_text=request_text,
        )
        async with self._lock:
            if run_id in self._records:
                raise ValueError(f"Run already exists: {run_id}")
            self._records[run_id] = record
        return record

    async def complete(self, run_id: UUID, result: AgentRunResult) -> StoredAgentRun:
        existing = await self._require(run_id)
        record = StoredAgentRun(
            run_id=run_id,
            thread_id=existing.thread_id,
            status=_to_public_status(result),
            data_classification=existing.data_classification,
            model_profile=existing.model_profile,
            request_text=existing.request_text,
            result=result,
            approval_request=None,
        )
        return await self._replace_existing(record)

    async def fail(self, run_id: UUID, error_code: str) -> StoredAgentRun:
        existing = await self._require(run_id)
        record = StoredAgentRun(
            run_id=run_id,
            thread_id=existing.thread_id,
            status=RunStatus.FAILED,
            data_classification=existing.data_classification,
            model_profile=existing.model_profile,
            request_text=existing.request_text,
            error_code=error_code,
            approval_request=None,
        )
        return await self._replace_existing(record)

    async def get(self, run_id: UUID) -> StoredAgentRun | None:
        async with self._lock:
            return self._records.get(run_id)

    async def wait_for_approval(
        self, run_id: UUID, approval_request: dict[str, object]
    ) -> StoredAgentRun:
        existing = await self._require(run_id)
        record = replace(
            existing,
            status=RunStatus.WAITING_FOR_APPROVAL,
            approval_request=approval_request,
        )
        return await self._replace_existing(record)

    async def claim_resume(self, run_id: UUID) -> StoredAgentRun | None:
        async with self._lock:
            existing = self._records.get(run_id)
            if (
                existing is None
                or existing.status is not RunStatus.WAITING_FOR_APPROVAL
            ):
                return None
            record = replace(existing, status=RunStatus.RUNNING)
            self._records[run_id] = record
            return record

    async def bind_execution_context(
        self,
        run_id: UUID,
        *,
        data_classification: DataClassification,
        model_profile: str,
    ) -> StoredAgentRun:
        existing = await self._require(run_id)
        if data_classification < existing.data_classification:
            raise ValueError("Run data classification must not be downgraded")
        return await self._replace_existing(
            StoredAgentRun(
                run_id=existing.run_id,
                thread_id=existing.thread_id,
                status=existing.status,
                data_classification=data_classification,
                model_profile=model_profile,
                request_text=existing.request_text,
                result=existing.result,
                error_code=existing.error_code,
                approval_request=existing.approval_request,
            )
        )

    async def _require(self, run_id: UUID) -> StoredAgentRun:
        record = await self.get(run_id)
        if record is None:
            raise ValueError(f"Unknown run: {run_id}")
        return record

    async def _replace_existing(self, record: StoredAgentRun) -> StoredAgentRun:
        async with self._lock:
            if record.run_id not in self._records:
                raise ValueError(f"Unknown run: {record.run_id}")
            self._records[record.run_id] = record
        return record


def _to_public_status(result: AgentRunResult) -> RunStatus:
    if result.status.value == "SUCCESS":
        return RunStatus.SUCCESS
    return RunStatus.LIMIT_REACHED

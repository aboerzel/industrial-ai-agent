"""Focused in-memory lifecycle store for local API agent runs."""

import asyncio
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from industrial_ai_agent.agent.agent_run import AgentRunResult
from industrial_ai_agent.infrastructure.api.schemas import RunStatus


@dataclass(frozen=True, slots=True)
class StoredAgentRun:
    run_id: UUID
    status: RunStatus
    result: AgentRunResult | None = None
    error_code: str | None = None


class AgentRunStore(Protocol):
    """Persistence boundary for API run lifecycle records."""

    async def create(self, run_id: UUID) -> StoredAgentRun: ...

    async def complete(
        self, run_id: UUID, result: AgentRunResult
    ) -> StoredAgentRun: ...

    async def fail(self, run_id: UUID, error_code: str) -> StoredAgentRun: ...

    async def get(self, run_id: UUID) -> StoredAgentRun | None: ...


class InMemoryAgentRunStore:
    """Development/demo-only store; records vanish when the API process stops."""

    def __init__(self) -> None:
        self._records: dict[UUID, StoredAgentRun] = {}
        self._lock = asyncio.Lock()

    async def create(self, run_id: UUID) -> StoredAgentRun:
        record = StoredAgentRun(run_id=run_id, status=RunStatus.RUNNING)
        async with self._lock:
            if run_id in self._records:
                raise ValueError(f"Run already exists: {run_id}")
            self._records[run_id] = record
        return record

    async def complete(self, run_id: UUID, result: AgentRunResult) -> StoredAgentRun:
        record = StoredAgentRun(
            run_id=run_id,
            status=_to_public_status(result),
            result=result,
        )
        return await self._replace_existing(record)

    async def fail(self, run_id: UUID, error_code: str) -> StoredAgentRun:
        record = StoredAgentRun(
            run_id=run_id,
            status=RunStatus.FAILED,
            error_code=error_code,
        )
        return await self._replace_existing(record)

    async def get(self, run_id: UUID) -> StoredAgentRun | None:
        async with self._lock:
            return self._records.get(run_id)

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

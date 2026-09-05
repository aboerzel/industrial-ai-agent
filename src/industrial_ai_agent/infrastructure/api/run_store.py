"""Application-facing lifecycle port for durable agent runs."""

import asyncio
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID

from industrial_ai_agent.agent.agent_run import AgentRunResult
from industrial_ai_agent.agent.run_classification_policy import AgentRunProfile
from industrial_ai_agent.domain.security import DataClassification
from industrial_ai_agent.infrastructure.api.schemas import RunStatus


@dataclass(frozen=True, slots=True)
class StoredAgentRun:
    run_id: UUID
    thread_id: UUID
    status: RunStatus
    data_classification: DataClassification
    run_profile: AgentRunProfile = AgentRunProfile.CONFIDENTIAL_TROUBLESHOOTING
    model_profile: str | None = None
    request_text: str = ""
    result: AgentRunResult | None = None
    error_code: str | None = None
    approval_request: dict[str, object] | None = None
    approval_action: str | None = None
    approval_decision: str | None = None
    approval_requested_at: datetime | None = None
    approval_decided_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class RuntimeRunInspection:
    """Payload-free read model for operational inspection of one persisted run."""

    run_id: UUID
    thread_id: UUID
    status: RunStatus
    data_classification: DataClassification
    run_profile: AgentRunProfile
    model_profile: str | None
    tool_call_count: int
    tool_names: tuple[str, ...]
    error_code: str | None
    approval_action: str | None
    approval_decision: str | None
    approval_requested_at: datetime | None
    approval_decided_at: datetime | None
    created_at: datetime | None
    updated_at: datetime | None


@dataclass(frozen=True, slots=True)
class RecentRuntimeRunsQuery:
    """Bounded application query constructed only from validated MCP filters."""

    status: RunStatus | None
    data_classification: DataClassification | None
    model_profile: str | None
    created_after: datetime
    limit: int


class AgentRunStore(Protocol):
    """Persistence boundary for API run lifecycle records."""

    async def create(
        self,
        run_id: UUID,
        *,
        request_text: str = "",
        data_classification: DataClassification = DataClassification.CONFIDENTIAL,
        run_profile: AgentRunProfile = AgentRunProfile.CONFIDENTIAL_TROUBLESHOOTING,
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
        run_profile: AgentRunProfile,
        model_profile: str,
    ) -> StoredAgentRun: ...

    async def get(self, run_id: UUID) -> StoredAgentRun | None: ...

    async def wait_for_approval(
        self, run_id: UUID, approval_request: dict[str, object]
    ) -> StoredAgentRun: ...

    async def claim_resume(
        self, run_id: UUID, *, decision: str
    ) -> StoredAgentRun | None: ...

    async def inspect(self, run_id: UUID) -> RuntimeRunInspection | None: ...

    async def list_recent(
        self, query: RecentRuntimeRunsQuery
    ) -> tuple[RuntimeRunInspection, ...]: ...


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
        run_profile: AgentRunProfile = AgentRunProfile.CONFIDENTIAL_TROUBLESHOOTING,
        model_profile: str | None = None,
    ) -> StoredAgentRun:
        record = StoredAgentRun(
            run_id=run_id,
            thread_id=run_id,
            status=RunStatus.RUNNING,
            data_classification=data_classification,
            run_profile=run_profile,
            model_profile=model_profile,
            request_text=request_text,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
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
            run_profile=existing.run_profile,
            model_profile=existing.model_profile,
            request_text=existing.request_text,
            result=result,
            approval_request=None,
            approval_action=existing.approval_action,
            approval_decision=existing.approval_decision,
            approval_requested_at=existing.approval_requested_at,
            approval_decided_at=existing.approval_decided_at,
            created_at=existing.created_at,
            updated_at=datetime.now(UTC),
        )
        return await self._replace_existing(record)

    async def fail(self, run_id: UUID, error_code: str) -> StoredAgentRun:
        existing = await self._require(run_id)
        record = StoredAgentRun(
            run_id=run_id,
            thread_id=existing.thread_id,
            status=RunStatus.FAILED,
            data_classification=existing.data_classification,
            run_profile=existing.run_profile,
            model_profile=existing.model_profile,
            request_text=existing.request_text,
            error_code=error_code,
            approval_request=None,
            approval_action=existing.approval_action,
            approval_decision=existing.approval_decision,
            approval_requested_at=existing.approval_requested_at,
            approval_decided_at=existing.approval_decided_at,
            created_at=existing.created_at,
            updated_at=datetime.now(UTC),
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
            approval_action=_approval_action(approval_request),
            approval_decision=None,
            approval_requested_at=datetime.now(UTC),
            approval_decided_at=None,
            updated_at=datetime.now(UTC),
        )
        return await self._replace_existing(record)

    async def claim_resume(
        self, run_id: UUID, *, decision: str
    ) -> StoredAgentRun | None:
        async with self._lock:
            existing = self._records.get(run_id)
            if (
                existing is None
                or existing.status is not RunStatus.WAITING_FOR_APPROVAL
            ):
                return None
            record = replace(
                existing,
                status=RunStatus.RUNNING,
                approval_request=None,
                approval_decision=decision,
                approval_decided_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
            )
            self._records[run_id] = record
            return record

    async def inspect(self, run_id: UUID) -> RuntimeRunInspection | None:
        record = await self.get(run_id)
        return _inspection(record) if record is not None else None

    async def list_recent(
        self, query: RecentRuntimeRunsQuery
    ) -> tuple[RuntimeRunInspection, ...]:
        async with self._lock:
            records = tuple(self._records.values())
        return tuple(
            _inspection(record)
            for record in records
            if _matches_recent_query(record, query)
        )[: query.limit]

    async def bind_execution_context(
        self,
        run_id: UUID,
        *,
        data_classification: DataClassification,
        run_profile: AgentRunProfile,
        model_profile: str,
    ) -> StoredAgentRun:
        existing = await self._require(run_id)
        if data_classification is not existing.data_classification:
            raise ValueError("Run data classification must not change")
        if run_profile is not existing.run_profile:
            raise ValueError("Run profile must not change")
        return await self._replace_existing(
            StoredAgentRun(
                run_id=existing.run_id,
                thread_id=existing.thread_id,
                status=existing.status,
                data_classification=data_classification,
                run_profile=run_profile,
                model_profile=model_profile,
                request_text=existing.request_text,
                result=existing.result,
                error_code=existing.error_code,
                approval_request=existing.approval_request,
                approval_action=existing.approval_action,
                approval_decision=existing.approval_decision,
                approval_requested_at=existing.approval_requested_at,
                approval_decided_at=existing.approval_decided_at,
                created_at=existing.created_at,
                updated_at=datetime.now(UTC),
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


def _inspection(record: StoredAgentRun) -> RuntimeRunInspection:
    return RuntimeRunInspection(
        run_id=record.run_id,
        thread_id=record.thread_id,
        status=record.status,
        data_classification=record.data_classification,
        run_profile=record.run_profile,
        model_profile=record.model_profile,
        tool_call_count=len(record.result.executed_tool_calls)
        if record.result is not None
        else 0,
        tool_names=tuple(call.tool for call in record.result.executed_tool_calls)
        if record.result is not None
        else (),
        error_code=record.error_code,
        approval_action=record.approval_action,
        approval_decision=record.approval_decision,
        approval_requested_at=record.approval_requested_at,
        approval_decided_at=record.approval_decided_at,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


def _matches_recent_query(record: StoredAgentRun, query: RecentRuntimeRunsQuery) -> bool:
    if query.status is not None and record.status is not query.status:
        return False
    if (
        query.data_classification is not None
        and record.data_classification is not query.data_classification
    ):
        return False
    if query.model_profile is not None and record.model_profile != query.model_profile:
        return False
    return record.created_at is None or record.created_at >= query.created_after


def _approval_action(approval_request: dict[str, object]) -> str | None:
    action = approval_request.get("action")
    return action if isinstance(action, str) else None

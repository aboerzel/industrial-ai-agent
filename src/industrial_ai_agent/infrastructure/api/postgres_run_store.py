"""SQLAlchemy-backed durable store for FastAPI agent-run lifecycle records."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select, update

from industrial_ai_agent.agent.agent_run import AgentRunResult
from industrial_ai_agent.domain.security import DataClassification, SecurityContext
from industrial_ai_agent.infrastructure.api.run_store import (
    AgentRunStore,
    RecentRuntimeRunsQuery,
    RuntimeRunInspection,
    StoredAgentRun,
    _to_public_status,
)
from industrial_ai_agent.infrastructure.api.schemas import RunStatus
from industrial_ai_agent.infrastructure.persistence.models import AgentRunRecord
from industrial_ai_agent.infrastructure.persistence.postgres import (
    PostgreSqlSessionFactory,
)


class PostgreSqlAgentRunStore(AgentRunStore):
    """Persist application records while PostgreSQL RLS enforces clearance."""

    def __init__(
        self,
        session_factory: PostgreSqlSessionFactory,
        security_context: SecurityContext,
    ) -> None:
        self._session_factory = session_factory
        self._security_context = security_context

    async def create(
        self,
        run_id: UUID,
        *,
        request_text: str = "",
        data_classification: DataClassification = DataClassification.CONFIDENTIAL,
        model_profile: str | None = None,
    ) -> StoredAgentRun:
        return await asyncio.to_thread(
            self._create,
            run_id,
            request_text,
            data_classification,
            model_profile,
        )

    def _create(
        self,
        run_id: UUID,
        request_text: str,
        data_classification: DataClassification,
        model_profile: str | None,
    ) -> StoredAgentRun:
        with self._session_factory.session(self._security_context) as session:
            record = AgentRunRecord(
                run_id=run_id,
                thread_id=run_id,
                status=RunStatus.RUNNING.value,
                data_classification=int(data_classification),
                model_profile=model_profile,
                request_text=request_text,
                final_answer=None,
                error_code=None,
                error_message=None,
                tool_call_summary=[],
                approval_payload=None,
                approval_action=None,
                approval_decision=None,
                approval_requested_at=None,
                approval_decided_at=None,
                interrupted_at=None,
                completed_at=None,
            )
            session.add(record)
            session.flush()
            return _stored(record)

    async def complete(self, run_id: UUID, result: AgentRunResult) -> StoredAgentRun:
        return await asyncio.to_thread(self._complete, run_id, result)

    def _complete(self, run_id: UUID, result: AgentRunResult) -> StoredAgentRun:
        with self._session_factory.session(self._security_context) as session:
            record = _require_record(session, run_id)
            record.status = _to_public_status(result).value
            record.final_answer = result.final_answer
            record.tool_call_summary = [
                call.model_dump() for call in result.executed_tool_calls
            ]
            record.approval_payload = None
            record.completed_at = datetime.now(UTC)
            return _stored(record)

    async def fail(self, run_id: UUID, error_code: str) -> StoredAgentRun:
        return await asyncio.to_thread(self._fail, run_id, error_code)

    def _fail(self, run_id: UUID, error_code: str) -> StoredAgentRun:
        with self._session_factory.session(self._security_context) as session:
            record = _require_record(session, run_id)
            record.status = RunStatus.FAILED.value
            record.error_code = error_code
            record.error_message = _safe_error_message(error_code)
            record.approval_payload = None
            record.completed_at = datetime.now(UTC)
            return _stored(record)

    async def bind_execution_context(
        self,
        run_id: UUID,
        *,
        data_classification: DataClassification,
        model_profile: str,
    ) -> StoredAgentRun:
        return await asyncio.to_thread(
            self._bind_execution_context, run_id, data_classification, model_profile
        )

    def _bind_execution_context(
        self,
        run_id: UUID,
        data_classification: DataClassification,
        model_profile: str,
    ) -> StoredAgentRun:
        with self._session_factory.session(self._security_context) as session:
            record = _require_record(session, run_id)
            if int(data_classification) < record.data_classification:
                raise ValueError("Run data classification must not be downgraded")
            if (
                record.model_profile is not None
                and record.model_profile != model_profile
            ):
                raise ValueError("Run model profile must not change")
            record.data_classification = int(data_classification)
            record.model_profile = model_profile
            return _stored(record)

    async def get(self, run_id: UUID) -> StoredAgentRun | None:
        return await asyncio.to_thread(self._get, run_id)

    def _get(self, run_id: UUID) -> StoredAgentRun | None:
        with self._session_factory.session(self._security_context) as session:
            record = session.scalar(
                select(AgentRunRecord).where(AgentRunRecord.run_id == run_id)
            )
            return _stored(record) if record is not None else None

    async def wait_for_approval(
        self, run_id: UUID, approval_request: dict[str, object]
    ) -> StoredAgentRun:
        return await asyncio.to_thread(
            self._wait_for_approval, run_id, approval_request
        )

    def _wait_for_approval(
        self, run_id: UUID, approval_request: dict[str, object]
    ) -> StoredAgentRun:
        with self._session_factory.session(self._security_context) as session:
            record = _require_record(session, run_id)
            record.status = RunStatus.WAITING_FOR_APPROVAL.value
            record.approval_payload = approval_request
            record.approval_action = _approval_action(approval_request)
            record.approval_decision = None
            record.interrupted_at = datetime.now(UTC)
            record.approval_requested_at = record.interrupted_at
            record.approval_decided_at = None
            return _stored(record)

    async def claim_resume(
        self, run_id: UUID, *, decision: str
    ) -> StoredAgentRun | None:
        return await asyncio.to_thread(self._claim_resume, run_id, decision)

    def _claim_resume(self, run_id: UUID, decision: str) -> StoredAgentRun | None:
        with self._session_factory.session(self._security_context) as session:
            changed = session.execute(
                update(AgentRunRecord)
                .where(
                    AgentRunRecord.run_id == run_id,
                    AgentRunRecord.status == RunStatus.WAITING_FOR_APPROVAL.value,
                )
                .values(
                    status=RunStatus.RUNNING.value,
                    approval_payload=None,
                    approval_decision=decision,
                    approval_decided_at=datetime.now(UTC),
                )
            ).rowcount
            if changed != 1:
                return None
            return _stored(_require_record(session, run_id))

    async def inspect(self, run_id: UUID) -> RuntimeRunInspection | None:
        return await asyncio.to_thread(self._inspect, run_id)

    def _inspect(self, run_id: UUID) -> RuntimeRunInspection | None:
        with self._session_factory.session(self._security_context) as session:
            record = session.scalar(
                select(AgentRunRecord).where(AgentRunRecord.run_id == run_id)
            )
            return _inspection(record) if record is not None else None

    async def list_recent(
        self, query: RecentRuntimeRunsQuery
    ) -> tuple[RuntimeRunInspection, ...]:
        return await asyncio.to_thread(self._list_recent, query)

    def _list_recent(
        self, query: RecentRuntimeRunsQuery
    ) -> tuple[RuntimeRunInspection, ...]:
        statement = select(AgentRunRecord).where(
            AgentRunRecord.created_at >= query.created_after
        )
        if query.status is not None:
            statement = statement.where(AgentRunRecord.status == query.status.value)
        if query.data_classification is not None:
            statement = statement.where(
                AgentRunRecord.data_classification == int(query.data_classification)
            )
        if query.model_profile is not None:
            statement = statement.where(AgentRunRecord.model_profile == query.model_profile)
        statement = statement.order_by(AgentRunRecord.created_at.desc()).limit(query.limit)
        with self._session_factory.session(self._security_context) as session:
            return tuple(_inspection(record) for record in session.scalars(statement))


def _require_record(session, run_id: UUID) -> AgentRunRecord:
    record = session.scalar(
        select(AgentRunRecord).where(AgentRunRecord.run_id == run_id)
    )
    if record is None:
        raise ValueError(f"Unknown run: {run_id}")
    return record


def _stored(record: AgentRunRecord) -> StoredAgentRun:
    result = None
    if record.status in {RunStatus.SUCCESS.value, RunStatus.LIMIT_REACHED.value}:
        result = AgentRunResult.model_validate(
            {
                "status": "SUCCESS"
                if record.status == RunStatus.SUCCESS.value
                else "LIMIT_REACHED",
                "final_answer": record.final_answer,
                "tool_call_count": len(record.tool_call_summary),
                "executed_tool_calls": record.tool_call_summary,
                "model_profile_name": record.model_profile,
            }
        )
    return StoredAgentRun(
        run_id=record.run_id,
        thread_id=record.thread_id,
        status=RunStatus(record.status),
        data_classification=DataClassification(record.data_classification),
        model_profile=record.model_profile,
        request_text=record.request_text,
        result=result,
        error_code=record.error_code,
        approval_request=record.approval_payload,
        approval_action=record.approval_action,
        approval_decision=record.approval_decision,
        approval_requested_at=record.approval_requested_at,
        approval_decided_at=record.approval_decided_at,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


def _safe_error_message(error_code: str) -> str:
    return {
        "no_eligible_model": "No eligible model is available for this request.",
        "model_egress_denied": "Model execution is not permitted for this request.",
        "mcp_service_unavailable": "A required MCP service is unavailable.",
    }.get(error_code, "The agent run could not be completed.")


def _inspection(record: AgentRunRecord) -> RuntimeRunInspection:
    return RuntimeRunInspection(
        run_id=record.run_id,
        thread_id=record.thread_id,
        status=RunStatus(record.status),
        data_classification=DataClassification(record.data_classification),
        model_profile=record.model_profile,
        tool_call_count=len(record.tool_call_summary)
        if isinstance(record.tool_call_summary, list)
        else 0,
        tool_names=_safe_tool_names(record.tool_call_summary),
        error_code=record.error_code,
        approval_action=_safe_approval_action(record.approval_action)
        or _approval_action(record.approval_payload),
        approval_decision=_safe_approval_decision(record.approval_decision),
        approval_requested_at=record.approval_requested_at or record.interrupted_at,
        approval_decided_at=record.approval_decided_at,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


_KNOWN_TOOL_NAMES = frozenset(
    {
        "get_product_history",
        "get_machine_status",
        "search_documentation",
        "create_maintenance_ticket",
    }
)


def _safe_tool_names(summary: object) -> tuple[str, ...]:
    if not isinstance(summary, list):
        return ()
    return tuple(
        entry["tool"]
        for entry in summary
        if isinstance(entry, dict) and entry.get("tool") in _KNOWN_TOOL_NAMES
    )


def _safe_approval_action(value: object) -> str | None:
    return value if value == "create_maintenance_ticket" else None


def _safe_approval_decision(value: object) -> str | None:
    return value if value in {"approve", "reject"} else None


def _approval_action(approval_request: object) -> str | None:
    if not isinstance(approval_request, dict):
        return None
    action = approval_request.get("action")
    return _safe_approval_action(action)

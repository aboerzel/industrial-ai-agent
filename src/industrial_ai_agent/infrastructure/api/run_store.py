"""Application-facing lifecycle port for durable agent runs."""

import asyncio
from copy import deepcopy
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID, uuid4

from industrial_ai_agent.agent.agent_run import AgentRunResult
from industrial_ai_agent.agent.failure_origin import (
    FailureOrigin,
    failure_origin_for_error_code,
)
from industrial_ai_agent.agent.response_language import ResponseLanguage
from industrial_ai_agent.agent.run_classification_policy import AgentRunProfile
from industrial_ai_agent.application.action_approval import (
    MaintenanceTicketApprovalClaim,
    ProtectedActionApprovalClaim,
    ReferenceCalibrationApprovalClaim,
    is_action_profile_authorized,
)
from industrial_ai_agent.application.run_visibility import is_run_visible
from industrial_ai_agent.domain.security import DataClassification, SecurityContext
from industrial_ai_agent.infrastructure.api.schemas import RunStatus


@dataclass(frozen=True, slots=True)
class StoredAgentRun:
    run_id: UUID
    thread_id: UUID
    investigation_id: UUID
    investigation_sequence: int
    status: RunStatus
    data_classification: DataClassification
    run_profile: AgentRunProfile = AgentRunProfile.CONFIDENTIAL_TROUBLESHOOTING
    model_profile: str | None = None
    request_text: str = ""
    response_language: ResponseLanguage = ResponseLanguage.EN
    result: AgentRunResult | None = None
    error_code: str | None = None
    failure_origin: FailureOrigin | None = None
    approval_request: dict[str, object] | None = None
    approval_action: str | None = None
    approval_decision: str | None = None
    approval_requested_at: datetime | None = None
    approval_decided_at: datetime | None = None
    approval_decided_clearance: DataClassification | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    approval_generations: dict[str, dict[str, object]] = field(default_factory=dict)


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
    failure_origin: FailureOrigin | None = None


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
        investigation_id: UUID | None = None,
        request_text: str = "",
        data_classification: DataClassification = DataClassification.CONFIDENTIAL,
        run_profile: AgentRunProfile = AgentRunProfile.CONFIDENTIAL_TROUBLESHOOTING,
        model_profile: str | None = None,
        response_language: ResponseLanguage = ResponseLanguage.EN,
    ) -> StoredAgentRun: ...

    async def complete(
        self, run_id: UUID, result: AgentRunResult
    ) -> StoredAgentRun: ...

    async def fail(
        self,
        run_id: UUID,
        error_code: str,
        *,
        failure_origin: FailureOrigin | None = None,
    ) -> StoredAgentRun: ...

    async def bind_execution_context(
        self,
        run_id: UUID,
        *,
        data_classification: DataClassification,
        run_profile: AgentRunProfile,
        model_profile: str,
    ) -> StoredAgentRun: ...

    async def get(self, run_id: UUID) -> StoredAgentRun | None: ...

    async def list_investigation(
        self, investigation_id: UUID
    ) -> tuple[StoredAgentRun, ...]: ...

    async def wait_for_approval(
        self,
        run_id: UUID,
        approval_request: dict[str, object],
        *,
        approval_execution_id: UUID | None = None,
    ) -> StoredAgentRun: ...

    async def claim_resume(
        self,
        run_id: UUID,
        *,
        decision: str,
        approval_clearance: DataClassification,
    ) -> StoredAgentRun | None: ...

    async def claim_protected_action_approval(
        self,
        claim: ProtectedActionApprovalClaim,
        *,
        security_context: SecurityContext,
    ) -> bool: ...

    async def is_consumed_protected_action_approval(
        self, claim: ProtectedActionApprovalClaim, *, security_context: SecurityContext
    ) -> bool: ...

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
        investigation_id: UUID | None = None,
        request_text: str = "",
        data_classification: DataClassification = DataClassification.CONFIDENTIAL,
        run_profile: AgentRunProfile = AgentRunProfile.CONFIDENTIAL_TROUBLESHOOTING,
        model_profile: str | None = None,
        response_language: ResponseLanguage = ResponseLanguage.EN,
    ) -> StoredAgentRun:
        resolved_investigation_id = investigation_id or run_id
        async with self._lock:
            if run_id in self._records:
                raise ValueError(f"Run already exists: {run_id}")
            sequence = (
                sum(
                    record.investigation_id == resolved_investigation_id
                    for record in self._records.values()
                )
                + 1
            )
            record = StoredAgentRun(
                run_id=run_id,
                thread_id=run_id,
                investigation_id=resolved_investigation_id,
                investigation_sequence=sequence,
                status=RunStatus.RUNNING,
                data_classification=data_classification,
                run_profile=run_profile,
                model_profile=model_profile,
                request_text=request_text,
                response_language=response_language,
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
            )
            self._records[run_id] = record
        return _approval_snapshot(record)

    async def complete(self, run_id: UUID, result: AgentRunResult) -> StoredAgentRun:
        existing = await self._require(run_id)
        record = StoredAgentRun(
            run_id=run_id,
            thread_id=existing.thread_id,
            investigation_id=existing.investigation_id,
            investigation_sequence=existing.investigation_sequence,
            status=_to_public_status(result),
            data_classification=existing.data_classification,
            run_profile=existing.run_profile,
            model_profile=existing.model_profile,
            request_text=existing.request_text,
            response_language=existing.response_language,
            result=result,
            error_code=recovery_failure_code(result),
            failure_origin=None,
            approval_request=None,
            approval_action=existing.approval_action,
            approval_decision=existing.approval_decision,
            approval_requested_at=existing.approval_requested_at,
            approval_decided_at=existing.approval_decided_at,
            approval_decided_clearance=existing.approval_decided_clearance,
            created_at=existing.created_at,
            updated_at=datetime.now(UTC),
        )
        return await self._replace_existing(record)

    async def fail(
        self,
        run_id: UUID,
        error_code: str,
        *,
        failure_origin: FailureOrigin | None = None,
    ) -> StoredAgentRun:
        existing = await self._require(run_id)
        record = StoredAgentRun(
            run_id=run_id,
            thread_id=existing.thread_id,
            investigation_id=existing.investigation_id,
            investigation_sequence=existing.investigation_sequence,
            status=RunStatus.FAILED,
            data_classification=existing.data_classification,
            run_profile=existing.run_profile,
            model_profile=existing.model_profile,
            request_text=existing.request_text,
            response_language=existing.response_language,
            error_code=error_code,
            failure_origin=failure_origin or failure_origin_for_error_code(error_code),
            approval_request=None,
            approval_action=existing.approval_action,
            approval_decision=existing.approval_decision,
            approval_requested_at=existing.approval_requested_at,
            approval_decided_at=existing.approval_decided_at,
            approval_decided_clearance=existing.approval_decided_clearance,
            created_at=existing.created_at,
            updated_at=datetime.now(UTC),
        )
        return await self._replace_existing(record)

    async def get(self, run_id: UUID) -> StoredAgentRun | None:
        async with self._lock:
            record = self._records.get(run_id)
            return _approval_snapshot(record) if record is not None else None

    async def list_investigation(
        self, investigation_id: UUID
    ) -> tuple[StoredAgentRun, ...]:
        async with self._lock:
            return tuple(
                sorted(
                    (
                        _approval_snapshot(record)
                        for record in self._records.values()
                        if record.investigation_id == investigation_id
                    ),
                    key=lambda record: record.investigation_sequence,
                )
            )

    async def wait_for_approval(
        self,
        run_id: UUID,
        approval_request: dict[str, object],
        *,
        approval_execution_id: UUID | None = None,
    ) -> StoredAgentRun:
        async with self._lock:
            existing = self._records.get(run_id)
            if existing is None:
                raise ValueError(f"Unknown run: {run_id}")
            payload, history, created = _new_approval_generation(
                existing, approval_request, approval_execution_id
            )
            if not created:
                return _approval_snapshot(existing)
            record = replace(
                existing,
                status=RunStatus.WAITING_FOR_APPROVAL,
                approval_request=payload,
                approval_generations=history,
                approval_action=_approval_action(payload),
                approval_decision=None,
                approval_requested_at=datetime.now(UTC),
                approval_decided_at=None,
                approval_decided_clearance=None,
                updated_at=datetime.now(UTC),
            )
            self._records[run_id] = record
            return _approval_snapshot(record)

    async def claim_resume(
        self,
        run_id: UUID,
        *,
        decision: str,
        approval_clearance: DataClassification,
    ) -> StoredAgentRun | None:
        async with self._lock:
            existing = self._records.get(run_id)
            if (
                existing is None
                or existing.status is not RunStatus.WAITING_FOR_APPROVAL
                or not _has_current_generation(existing)
            ):
                return None
            record = replace(
                existing,
                status=RunStatus.RUNNING,
                approval_decision=decision,
                approval_decided_at=datetime.now(UTC),
                approval_decided_clearance=approval_clearance,
                approval_generations=_decide_approval_generation(
                    existing, decision, approval_clearance
                ),
                updated_at=datetime.now(UTC),
            )
            self._records[run_id] = record
            return _approval_snapshot(record)

    async def claim_protected_action_approval(
        self,
        claim: ProtectedActionApprovalClaim,
        *,
        security_context: SecurityContext,
    ) -> bool:
        async with self._lock:
            existing = self._records.get(claim.run_id)
            if existing is None or not _matches_protected_action_approval(
                existing, claim, security_context
            ):
                return False
            self._records[claim.run_id] = replace(
                existing,
                approval_request=None,
                approval_generations=_consume_approval_generation(existing, claim),
                updated_at=datetime.now(UTC),
            )
            return True

    async def is_consumed_protected_action_approval(
        self, claim: ProtectedActionApprovalClaim, *, security_context: SecurityContext
    ) -> bool:
        async with self._lock:
            record = self._records.get(claim.run_id)
            return record is not None and _matches_approval_generation(
                record, claim, security_context, consumed=True
            )

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
                investigation_id=existing.investigation_id,
                investigation_sequence=existing.investigation_sequence,
                status=existing.status,
                data_classification=data_classification,
                run_profile=run_profile,
                model_profile=model_profile,
                request_text=existing.request_text,
                response_language=existing.response_language,
                result=existing.result,
                error_code=existing.error_code,
                failure_origin=existing.failure_origin,
                approval_request=existing.approval_request,
                approval_action=existing.approval_action,
                approval_decision=existing.approval_decision,
                approval_requested_at=existing.approval_requested_at,
                approval_decided_at=existing.approval_decided_at,
                approval_decided_clearance=existing.approval_decided_clearance,
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
            # Lifecycle updates must not overwrite a concurrently consumed generation.
            record = replace(
                record,
                approval_generations=self._records[record.run_id].approval_generations,
            )
            self._records[record.run_id] = record
        return _approval_snapshot(record)


def _approval_snapshot(record: StoredAgentRun) -> StoredAgentRun:
    """Returned DTOs cannot mutate store-owned approval authority."""
    return replace(
        record,
        approval_request=deepcopy(record.approval_request),
        approval_generations=deepcopy(record.approval_generations),
    )


def _to_public_status(result: AgentRunResult) -> RunStatus:
    if result.status.value == "SUCCESS":
        return RunStatus.SUCCESS
    if result.status.value == "LIMIT_REACHED":
        return RunStatus.LIMIT_REACHED
    return RunStatus.FAILED


def recovery_failure_code(result: AgentRunResult) -> str | None:
    return {
        "EVIDENCE_REQUIREMENTS_UNSATISFIED": "evidence_requirements_unsatisfied",
        "EVIDENCE_SOURCE_UNAVAILABLE": "evidence_source_unavailable",
        "RECOVERY_INCOMPLETE": "recovery_incomplete",
        "RECOVERY_BLOCKED": "recovery_blocked",
        "RECOVERY_FAILED": "recovery_failed",
    }.get(result.status.value)


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
        failure_origin=record.failure_origin,
        approval_action=record.approval_action,
        approval_decision=record.approval_decision,
        approval_requested_at=record.approval_requested_at,
        approval_decided_at=record.approval_decided_at,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


def _matches_recent_query(
    record: StoredAgentRun, query: RecentRuntimeRunsQuery
) -> bool:
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


def _matches_protected_action_approval(
    record: StoredAgentRun,
    claim: ProtectedActionApprovalClaim,
    security_context: SecurityContext,
) -> bool:
    approval_request = record.approval_request
    if not isinstance(approval_request, dict):
        return False
    if not _matches_approval_generation(
        record, claim, security_context, consumed=False
    ):
        return False
    return (
        record.status is RunStatus.RUNNING
        and _has_current_generation(record)
        and record.approval_decision == "approve"
        and record.approval_decided_at is not None
        and isinstance(record.approval_decided_clearance, DataClassification)
        and record.approval_decided_clearance >= record.data_classification
        and record.approval_action == approval_request.get("action")
        and _generation_id(approval_request) == claim.action_id
    )


def _matches_approval_generation(
    record: StoredAgentRun,
    claim: ProtectedActionApprovalClaim,
    security_context: SecurityContext,
    *,
    consumed: bool,
) -> bool:
    generation = record.approval_generations.get(claim.action_id)
    if (
        not isinstance(generation, dict)
        or _generation_id(generation) != claim.action_id
    ):
        return False
    details = generation.get("arguments")
    if not isinstance(details, dict):
        return False
    if isinstance(claim, MaintenanceTicketApprovalClaim):
        action = "create_maintenance_ticket"
        target_matches = details.get("summary") == claim.summary
    elif isinstance(claim, ReferenceCalibrationApprovalClaim):
        action = "execute_reference_calibration"
        target_matches = (
            details.get("device_id") == claim.device_id.value
            and details.get("operation_type") == "reference_calibration"
        )
    else:
        return False
    return (
        record.run_id == claim.run_id
        and generation.get("run_id") == str(record.run_id)
        and generation.get("run_profile") == record.run_profile.value
        and generation.get("classification") == record.data_classification.name
        and generation.get("decision") == "approve"
        and isinstance(generation.get("decided_at"), str)
        and generation.get("consumed") is consumed
        and _generation_approver_clearance(generation) >= record.data_classification
        and is_run_visible(record.data_classification, security_context)
        and is_action_profile_authorized(
            action, record.data_classification, record.run_profile
        )
        and generation.get("action") == action
        and details.get("station_id") == claim.station_id.value
        and target_matches
    )


def _generation_approver_clearance(generation: dict[str, object]) -> int:
    value = generation.get("approver_clearance")
    if not isinstance(value, str) or value not in DataClassification.__members__:
        return -1
    return int(DataClassification[value])


def _generation_id(payload: dict[str, object] | None) -> str | None:
    value = payload.get("approval_execution_id") if isinstance(payload, dict) else None
    if not isinstance(value, str):
        return None
    try:
        return value if str(UUID(value)) == value else None
    except ValueError:
        return None


def _has_current_generation(record: StoredAgentRun) -> bool:
    identity = _generation_id(record.approval_request)
    generation = record.approval_generations.get(identity)
    payload = record.approval_request
    return (
        identity is not None
        and isinstance(generation, dict)
        and isinstance(payload, dict)
        and all(
            generation.get(key) == payload.get(key)
            for key in ("action", "action_id", "arguments")
        )
        and generation.get("run_id") == str(record.run_id)
        and generation.get("run_profile") == record.run_profile.value
        and generation.get("classification") == record.data_classification.name
    )


def _new_approval_generation(
    record: StoredAgentRun, request: dict[str, object], execution_id: UUID | None
) -> tuple[dict[str, object], dict[str, dict[str, object]], bool]:
    if execution_id is not None and not isinstance(execution_id, UUID):
        raise PermissionError("Invalid approval execution identity")
    identity = str(execution_id or uuid4())
    payload = deepcopy(request)
    # A model/user payload cannot choose its own generation; only the server keyword can.
    payload["approval_execution_id"] = identity
    binding = {
        "approval_execution_id": identity,
        "run_id": str(record.run_id),
        "run_profile": record.run_profile.value,
        "classification": record.data_classification.name,
        "action": payload.get("action"),
        "action_id": payload.get("action_id"),
        "arguments": deepcopy(payload.get("arguments")),
    }
    history = deepcopy(record.approval_generations)
    existing = history.get(identity)
    if existing is not None:
        if any(existing.get(key) != value for key, value in binding.items()):
            raise PermissionError("Approval execution identity cannot be rebound")
        return payload, history, False
    history[identity] = {
        **binding,
        "decision": None,
        "decided_at": None,
        "approver_clearance": None,
        "consumed": False,
    }
    return payload, history, True


def _decide_approval_generation(
    record: StoredAgentRun, decision: str, clearance: DataClassification
) -> dict[str, dict[str, object]]:
    history = deepcopy(record.approval_generations)
    generation = history[_generation_id(record.approval_request)]
    generation.update(
        decision=decision,
        decided_at=datetime.now(UTC).isoformat(),
        approver_clearance=clearance.name,
    )
    return history


def _consume_approval_generation(
    record: StoredAgentRun, claim: ProtectedActionApprovalClaim
) -> dict[str, dict[str, object]]:
    history = deepcopy(record.approval_generations)
    history[claim.action_id].update(
        consumed=True, consumed_at=datetime.now(UTC).isoformat()
    )
    return history


def _approval_action(approval_request: dict[str, object]) -> str | None:
    action = approval_request.get("action")
    return action if isinstance(action, str) else None

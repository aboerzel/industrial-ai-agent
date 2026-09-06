"""Bounded Application ports and safe observations for RCA evidence acquisition."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

from industrial_ai_agent.application.rca import (
    RcaApprovalState,
    RcaComponent,
    RcaMeasurementUnit,
    RcaOperation,
    RcaOperationStatus,
    RcaRuntimeStatus,
    RcaSeverity,
    RcaSpanAttribute,
)
from industrial_ai_agent.domain.security import DataClassification, SecurityContext


class RcaRunNotAccessibleError(PermissionError):
    """The caller may not inspect the requested run through the RLS-protected path."""


class RcaRuntimeEvidenceUnavailableError(RuntimeError):
    """Runtime evidence cannot establish the authorization gate for an RCA request."""


class RcaEvidenceUnavailableError(RuntimeError):
    """A bounded non-runtime evidence source is unavailable."""


class RcaEvidenceMissingError(RuntimeError):
    """A bounded source answered successfully but has no evidence for the run."""


class RcaEvidenceNotAuthorizedError(PermissionError):
    """A non-runtime evidence backend rejected its own service credentials."""


class RcaEvidenceMalformedError(RuntimeError):
    """A bounded source returned a response outside its safe expected projection."""


@dataclass(frozen=True, slots=True)
class RcaRuntimeObservation:
    run_id: UUID
    status: RcaRuntimeStatus
    data_classification: DataClassification
    run_profile: str | None
    model_profile: str | None
    created_at: datetime | None
    updated_at: datetime | None
    error_code: str | None
    tool_call_count: int
    approval_state: RcaApprovalState
    approval_requested_at: datetime | None
    approval_decided_at: datetime | None


@dataclass(frozen=True, slots=True)
class RcaToolTrajectoryObservation:
    sequence: int
    tool_name: str
    component: RcaComponent


@dataclass(frozen=True, slots=True)
class RcaSpanObservation:
    span_id: str
    parent_span_id: str | None
    operation: RcaOperation
    component: RcaComponent
    service: RcaComponent
    started_at: datetime
    duration_ms: float
    status: RcaOperationStatus
    error_type: str | None
    error_code: str | None
    safe_attributes: tuple[RcaSpanAttribute, ...] = ()


@dataclass(frozen=True, slots=True)
class RcaTraceObservation:
    trace_id: str
    spans: tuple[RcaSpanObservation, ...]
    truncated: bool


@dataclass(frozen=True, slots=True)
class RcaLogObservation:
    timestamp: datetime
    component: RcaComponent
    event_name: str
    severity: RcaSeverity
    error_code: str | None


@dataclass(frozen=True, slots=True)
class RcaMetricObservation:
    metric_name: str
    value: float
    unit: RcaMeasurementUnit
    window_start: datetime
    window_end: datetime


@dataclass(frozen=True, slots=True)
class RcaLlmGenerationObservation:
    """Safe metadata from one Langfuse generation; no input, output, or raw metadata."""

    model_name: str | None
    provider: str | None
    model_profile: str | None
    status: RcaOperationStatus
    started_at: datetime
    duration_ms: float
    input_tokens: int | None
    output_tokens: int | None
    total_tokens: int | None
    observed_cost_usd: float | None
    configured_api_cost_usd: float | None


@dataclass(frozen=True, slots=True)
class RcaLlmTraceObservation:
    """Bounded Langfuse projection for one already-authorized trace correlation."""

    trace_id_consistent: bool
    generations: tuple[RcaLlmGenerationObservation, ...]
    truncated: bool


class RuntimeRcaEvidencePort(Protocol):
    """RLS-gated runtime facts, queried before any telemetry correlation."""

    async def inspect_run(
        self, run_id: UUID, security_context: SecurityContext
    ) -> RcaRuntimeObservation:
        """Return safe runtime facts or fail closed when the run is inaccessible."""

    async def get_tool_trajectory(
        self, run_id: UUID, security_context: SecurityContext
    ) -> tuple[RcaToolTrajectoryObservation, ...]:
        """Return only ordered tool metadata without arguments or results."""


class TraceRcaEvidencePort(Protocol):
    """Bounded trace lookup after runtime authorization has established the run."""

    def get_run_trace(self, run_id: UUID) -> RcaTraceObservation:
        """Return one safe trace projection for an authorized run."""


class LogRcaEvidencePort(Protocol):
    """Bounded metadata-only logs for an already authorized trace."""

    def get_trace_logs(
        self, trace: RcaTraceObservation
    ) -> tuple[RcaLogObservation, ...]:
        """Return safe correlated log-event metadata only."""


class MetricRcaEvidencePort(Protocol):
    """Bounded metric context for an already authorized trace."""

    def get_trace_metrics(
        self, trace: RcaTraceObservation
    ) -> tuple[RcaMetricObservation, ...]:
        """Return fixed metric-context projections without query language input."""


class LlmEvidencePort(Protocol):
    """Bounded LLM metadata after Runtime RLS and trace correlation have succeeded."""

    def get_trace_llm_evidence(
        self,
        trace_id: str,
        *,
        from_time: datetime,
        to_time: datetime,
    ) -> RcaLlmTraceObservation:
        """Return safe Langfuse generation metadata for one authorized trace only."""

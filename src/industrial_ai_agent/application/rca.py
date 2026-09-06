"""Provider-independent, bounded contracts for automated run root-cause analysis."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Protocol, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from industrial_ai_agent.domain.security import DataClassification

EvidenceReference = Annotated[
    str, StringConstraints(pattern=r"^EV-[A-Z]+-[0-9]{3}$", strict=True)
]
FindingIdentifier = Annotated[
    str, StringConstraints(pattern=r"^F-[A-Z]+-[0-9]{3}$", strict=True)
]
TraceIdentifier = Annotated[
    str, StringConstraints(pattern=r"^[0-9a-f]{32}$", strict=True)
]
SpanIdentifier = Annotated[
    str, StringConstraints(pattern=r"^[0-9a-f]{16}$", strict=True)
]
SafeCode = Annotated[
    str, StringConstraints(pattern=r"^[A-Za-z][A-Za-z0-9_.-]{0,79}$", strict=True)
]
SafeName = Annotated[
    str, StringConstraints(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:/-]{0,159}$", strict=True)
]
BoundedText = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=500, strict=True),
]
RemediationText = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=240, strict=True),
]


class RcaEvidenceSource(StrEnum):
    RUNTIME = "runtime"
    TEMPO = "tempo"
    LOKI = "loki"
    PROMETHEUS = "prometheus"
    LANGFUSE = "langfuse"


class RcaEvidenceSourceStatus(StrEnum):
    AVAILABLE = "available"
    MISSING = "missing"
    UNAVAILABLE = "unavailable"
    MALFORMED = "malformed"
    NOT_AUTHORIZED = "not_authorized"
    NOT_APPLICABLE = "not_applicable"


class RcaLimitationCode(StrEnum):
    BACKEND_UNAVAILABLE = "backend_unavailable"
    DATA_NOT_RECORDED = "data_not_recorded"
    RESPONSE_MALFORMED = "response_malformed"
    ACCESS_NOT_AUTHORIZED = "access_not_authorized"
    SOURCE_NOT_APPLICABLE = "source_not_applicable"
    TRACE_INCOMPLETE = "trace_incomplete"
    TOKEN_USAGE_UNAVAILABLE = "token_usage_unavailable"
    COST_UNAVAILABLE = "cost_unavailable"
    CLASSIFICATION_UNKNOWN = "classification_unknown"
    NO_PERFORMANCE_BASELINE = "no_performance_baseline"
    OBSERVATION_LIMIT_REACHED = "observation_limit_reached"
    CORRELATION_MISMATCH = "correlation_mismatch"


class RcaFindingKind(StrEnum):
    """Epistemic status; an LLM must never promote a finding between these kinds."""

    OBSERVED = "observed"
    DERIVED = "derived"
    HYPOTHESIS = "hypothesis"
    CONFIRMED_RUN_CAUSE = "confirmed_run_cause"


class RcaFindingCategory(StrEnum):
    RUN_LIFECYCLE = "run_lifecycle"
    FAILURE = "failure"
    LATENCY = "latency"
    MCP = "mcp"
    RETRIEVAL = "retrieval"
    LLM = "llm"
    TOKEN_USAGE = "token_usage"
    COST = "cost"
    APPROVAL = "approval"
    PERSISTENCE = "persistence"
    TELEMETRY = "telemetry"


class RcaSeverity(StrEnum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class RcaConfidence(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class RcaComponent(StrEnum):
    AGENT_RUNTIME = "agent_runtime"
    MODEL_ROUTING = "model_routing"
    LLM = "llm"
    MCP = "mcp"
    MCP_DISCOVERY = "mcp_discovery"
    FACTORY_MCP = "factory_mcp"
    KNOWLEDGE_MCP = "knowledge_mcp"
    RETRIEVAL = "retrieval"
    APPROVAL = "approval"
    PERSISTENCE = "persistence"
    TELEMETRY = "telemetry"
    UNKNOWN = "unknown"


class RcaOperation(StrEnum):
    AGENT_RUN = "agent.run"
    MODEL_ROUTING = "model.routing"
    LLM_CALL = "llm.call"
    MCP_DISCOVERY = "mcp.discovery"
    MCP_TOOL = "mcp.tool"
    FACTORY_TOOL = "factory.tool"
    KNOWLEDGE_SEARCH = "knowledge.search"
    RETRIEVAL_SEARCH = "retrieval.search"
    RETRIEVAL_EMBEDDING = "retrieval.embedding"
    RETRIEVAL_LEXICAL = "retrieval.lexical"
    RETRIEVAL_SEMANTIC = "retrieval.semantic"
    RETRIEVAL_FUSION = "retrieval.fusion"
    RETRIEVAL_RERANK = "retrieval.rerank"
    APPROVAL_WAIT = "approval.wait"
    APPROVAL_RESUME = "approval.resume"
    MAINTENANCE_TICKET_CREATE = "maintenance_ticket.create"
    PERSISTENCE_RUN_STORE = "persistence.run_store"


class RcaOperationStatus(StrEnum):
    OK = "ok"
    ERROR = "error"
    UNSET = "unset"


class RcaSafeAttributeName(StrEnum):
    DATA_CLASSIFICATION = "data.classification"
    EXECUTION_ZONE = "execution.zone"
    MCP_OPERATION = "mcp.operation"
    MCP_SERVER = "mcp.server"
    MCP_TOOL = "mcp.tool"
    MODEL_NAME = "model.name"
    MODEL_PROVIDER = "model.provider"
    MODEL_PROFILE = "model.profile"
    OPERATION_STATUS = "operation.status"
    OPERATION_TYPE = "operation.type"
    PERSISTENCE_OPERATION = "persistence.operation"
    RETRIEVAL_STRATEGY = "retrieval.strategy"
    RUN_PROFILE = "run.profile"


class RcaRuntimeStatus(StrEnum):
    RUNNING = "running"
    WAITING_FOR_APPROVAL = "waiting_for_approval"
    SUCCESS = "success"
    LIMIT_REACHED = "limit_reached"
    FAILED = "failed"


class RcaRetrievalStage(StrEnum):
    SEARCH = "search"
    EMBEDDING = "embedding"
    LEXICAL = "lexical"
    SEMANTIC = "semantic"
    FUSION = "fusion"
    RERANK = "rerank"


class RcaApprovalState(StrEnum):
    NONE = "none"
    WAITING = "waiting"
    APPROVED = "approved"
    REJECTED = "rejected"


class RcaMeasurementProvenance(StrEnum):
    OBSERVED = "observed"
    CONFIGURED = "configured"
    DERIVED = "derived"


class RcaMeasurementScope(StrEnum):
    RUN = "run"
    MODEL_CONFIGURATION = "model_configuration"


class RcaMeasurementName(StrEnum):
    RUN_DURATION_MS = "run_duration_ms"
    COMPONENT_DURATION_MS = "component_duration_ms"
    LATENCY_SHARE = "latency_share"
    INPUT_TOKENS = "input_tokens"
    OUTPUT_TOKENS = "output_tokens"
    TOTAL_TOKENS = "total_tokens"
    API_COST_USD = "api_cost_usd"
    APPROVAL_WAIT_MS = "approval_wait_ms"
    GENERATION_COUNT = "generation_count"


class RcaMeasurementUnit(StrEnum):
    COUNT = "count"
    MILLISECONDS = "milliseconds"
    SECONDS = "seconds"
    RATIO = "ratio"
    USD = "usd"


class RcaAnalysisStatus(StrEnum):
    COMPLETE = "complete"
    PARTIAL = "partial"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"


class _RcaModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class RcaSourceAvailability(_RcaModel):
    evidence_ref: EvidenceReference
    source: RcaEvidenceSource
    status: RcaEvidenceSourceStatus
    limitations: tuple[RcaLimitationCode, ...] = Field(default=(), max_length=5)


class RcaRuntimeEvidence(_RcaModel):
    evidence_ref: EvidenceReference
    status: RcaRuntimeStatus
    run_profile: SafeName | None = None
    model_profile: SafeName | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    error_code: SafeCode | None = None
    tool_call_count: int = Field(ge=0, le=100)


class RcaSpanAttribute(_RcaModel):
    name: RcaSafeAttributeName
    value: SafeName | int | float | bool


class RcaTraceSpanEvidence(_RcaModel):
    evidence_ref: EvidenceReference
    span_id: SpanIdentifier
    parent_span_id: SpanIdentifier | None = None
    operation: RcaOperation
    component: RcaComponent
    service: RcaComponent
    started_at: datetime
    duration_ms: float = Field(ge=0, le=86_400_000)
    status: RcaOperationStatus
    error_type: SafeCode | None = None
    error_code: SafeCode | None = None
    safe_attributes: tuple[RcaSpanAttribute, ...] = Field(default=(), max_length=11)


class RcaMcpToolEvidence(_RcaModel):
    evidence_ref: EvidenceReference
    sequence: int = Field(ge=1, le=100)
    tool_name: SafeName
    component: RcaComponent
    status: RcaOperationStatus
    duration_ms: float | None = Field(default=None, ge=0, le=86_400_000)


class RcaRetrievalStageEvidence(_RcaModel):
    evidence_ref: EvidenceReference
    stage: RcaRetrievalStage
    status: RcaOperationStatus
    duration_ms: float = Field(ge=0, le=86_400_000)
    candidate_count: int | None = Field(default=None, ge=0, le=10_000)
    result_count: int | None = Field(default=None, ge=0, le=10_000)


class RcaLogEvidence(_RcaModel):
    evidence_ref: EvidenceReference
    timestamp: datetime
    component: RcaComponent
    event_name: SafeName
    severity: RcaSeverity
    error_code: SafeCode | None = None


class RcaMetricEvidence(_RcaModel):
    evidence_ref: EvidenceReference
    metric_name: SafeName
    value: float = Field(ge=0)
    unit: RcaMeasurementUnit
    window_start: datetime
    window_end: datetime

    @model_validator(mode="after")
    def validate_window(self) -> Self:
        if self.window_end < self.window_start:
            raise ValueError("metric window end must not precede its start")
        return self


class RcaLlmEvidence(_RcaModel):
    evidence_ref: EvidenceReference
    provider: SafeName | None = None
    model_name: SafeName | None = None
    model_profile: SafeName | None = None
    status: RcaOperationStatus
    started_at: datetime
    duration_ms: float = Field(ge=0, le=86_400_000)


class RcaMeasurement(_RcaModel):
    evidence_ref: EvidenceReference
    name: RcaMeasurementName
    value: float = Field(ge=0)
    unit: RcaMeasurementUnit
    provenance: RcaMeasurementProvenance
    scope: RcaMeasurementScope

    @model_validator(mode="after")
    def validate_provenance_scope(self) -> Self:
        if (
            self.provenance is RcaMeasurementProvenance.CONFIGURED
            and self.scope is not RcaMeasurementScope.MODEL_CONFIGURATION
        ):
            raise ValueError(
                "configured measurements apply only to model configuration"
            )
        if (
            self.name is RcaMeasurementName.API_COST_USD
            and self.unit is not RcaMeasurementUnit.USD
        ):
            raise ValueError("api_cost_usd must use USD")
        if (
            self.name is RcaMeasurementName.LATENCY_SHARE
            and self.unit is not RcaMeasurementUnit.RATIO
        ):
            raise ValueError("latency_share must use ratio")
        return self


class RcaFailureEvidence(_RcaModel):
    evidence_ref: EvidenceReference
    component: RcaComponent
    service: RcaComponent
    operation: RcaOperation
    error_type: SafeCode | None = None
    error_code: SafeCode | None = None


class RcaApprovalEvidence(_RcaModel):
    evidence_ref: EvidenceReference
    state: RcaApprovalState
    requested_at: datetime | None = None
    decided_at: datetime | None = None

    @model_validator(mode="after")
    def validate_timing(self) -> Self:
        if (
            self.requested_at is not None
            and self.decided_at is not None
            and self.decided_at < self.requested_at
        ):
            raise ValueError("approval decision must not precede its request")
        return self


class RcaTimingEvidence(_RcaModel):
    evidence_ref: EvidenceReference
    operation: RcaOperation
    component: RcaComponent
    started_at: datetime | None = None
    duration_ms: float = Field(ge=0, le=86_400_000)


class RcaEvidenceBundle(_RcaModel):
    """Safe report-local RCA evidence; all evidence references are local to this bundle."""

    run_id: UUID
    trace_id: TraceIdentifier | None = None
    trace_truncated: bool = False
    langfuse_trace_id_consistent: bool | None = None
    langfuse_truncated: bool = False
    data_classification: DataClassification | None = None
    source_availability: tuple[RcaSourceAvailability, ...]
    runtime: RcaRuntimeEvidence | None = None
    trace_spans: tuple[RcaTraceSpanEvidence, ...] = ()
    mcp_tools: tuple[RcaMcpToolEvidence, ...] = ()
    retrieval_stages: tuple[RcaRetrievalStageEvidence, ...] = ()
    correlated_logs: tuple[RcaLogEvidence, ...] = ()
    metrics: tuple[RcaMetricEvidence, ...] = ()
    llm_models: tuple[RcaLlmEvidence, ...] = ()
    measurements: tuple[RcaMeasurement, ...] = ()
    failures: tuple[RcaFailureEvidence, ...] = ()
    approval: RcaApprovalEvidence | None = None
    persistence_timings: tuple[RcaTimingEvidence, ...] = ()
    timings: tuple[RcaTimingEvidence, ...] = ()

    @model_validator(mode="after")
    def validate_sources_and_references(self) -> Self:
        sources = tuple(item.source for item in self.source_availability)
        if len(set(sources)) != len(sources) or set(sources) != set(RcaEvidenceSource):
            raise ValueError(
                "source availability must represent each RCA evidence source once"
            )
        references = self._evidence_references()
        if len(references) != len(set(references)):
            raise ValueError("evidence references must be unique within an RCA bundle")
        return self

    def evidence_references(self) -> frozenset[str]:
        """Return the report-local references a finding may cite."""
        return frozenset(self._evidence_references())

    def _evidence_references(self) -> tuple[str, ...]:
        items: tuple[object, ...] = (
            *self.source_availability,
            *((self.runtime,) if self.runtime is not None else ()),
            *self.trace_spans,
            *self.mcp_tools,
            *self.retrieval_stages,
            *self.correlated_logs,
            *self.metrics,
            *self.llm_models,
            *self.measurements,
            *self.failures,
            *((self.approval,) if self.approval is not None else ()),
            *self.persistence_timings,
            *self.timings,
        )
        return tuple(item.evidence_ref for item in items if isinstance(item, _RcaModel))


class RcaFinding(_RcaModel):
    finding_id: FindingIdentifier
    kind: RcaFindingKind
    category: RcaFindingCategory
    severity: RcaSeverity
    affected_component: RcaComponent
    statement: BoundedText
    confidence: RcaConfidence
    evidence_refs: tuple[EvidenceReference, ...] = Field(min_length=1, max_length=20)
    measurements: tuple[RcaMeasurement, ...] = Field(default=(), max_length=10)
    remediation_candidates: tuple[RemediationText, ...] = Field(
        default=(), max_length=5
    )
    limitations: tuple[RcaLimitationCode, ...] = Field(default=(), max_length=10)

    @model_validator(mode="after")
    def validate_evidence_references(self) -> Self:
        if len(self.evidence_refs) != len(set(self.evidence_refs)):
            raise ValueError("finding evidence references must be unique")
        return self


class RcaCompleteness(_RcaModel):
    available_sources: tuple[RcaEvidenceSource, ...]
    incomplete_sources: tuple[RcaEvidenceSource, ...]
    not_applicable_sources: tuple[RcaEvidenceSource, ...]

    @model_validator(mode="after")
    def validate_source_partition(self) -> Self:
        sources = (
            *self.available_sources,
            *self.incomplete_sources,
            *self.not_applicable_sources,
        )
        if len(set(sources)) != len(sources) or set(sources) != set(RcaEvidenceSource):
            raise ValueError("completeness must partition all RCA evidence sources")
        return self


class RcaAnalysisReport(_RcaModel):
    run_id: UUID
    trace_id: TraceIdentifier | None = None
    analysis_status: RcaAnalysisStatus
    evidence: RcaEvidenceBundle
    deterministic_findings: tuple[RcaFinding, ...] = ()
    overall_limitations: tuple[RcaLimitationCode, ...] = Field(
        default=(), max_length=20
    )
    completeness: RcaCompleteness

    @model_validator(mode="after")
    def validate_report(self) -> Self:
        if (
            self.run_id != self.evidence.run_id
            or self.trace_id != self.evidence.trace_id
        ):
            raise ValueError("report and evidence identifiers must match")
        known_references = self.evidence.evidence_references()
        unknown_references = {
            reference
            for finding in self.deterministic_findings
            for reference in finding.evidence_refs
            if reference not in known_references
        }
        if unknown_references:
            raise ValueError("findings may reference only evidence in this report")
        expected_available = tuple(
            item.source
            for item in self.evidence.source_availability
            if item.status is RcaEvidenceSourceStatus.AVAILABLE
        )
        expected_incomplete = tuple(
            item.source
            for item in self.evidence.source_availability
            if item.status
            not in {
                RcaEvidenceSourceStatus.AVAILABLE,
                RcaEvidenceSourceStatus.NOT_APPLICABLE,
            }
        )
        expected_not_applicable = tuple(
            item.source
            for item in self.evidence.source_availability
            if item.status is RcaEvidenceSourceStatus.NOT_APPLICABLE
        )
        if (
            self.completeness.available_sources != expected_available
            or self.completeness.incomplete_sources != expected_incomplete
            or self.completeness.not_applicable_sources != expected_not_applicable
        ):
            raise ValueError("report completeness must match source availability")
        if self.analysis_status is RcaAnalysisStatus.COMPLETE and expected_incomplete:
            raise ValueError(
                "complete RCA reports cannot have incomplete evidence sources"
            )
        has_incomplete_evidence = expected_incomplete or any(
            limitation in self.overall_limitations
            for limitation in (
                RcaLimitationCode.TRACE_INCOMPLETE,
                RcaLimitationCode.OBSERVATION_LIMIT_REACHED,
            )
        )
        if (
            self.analysis_status is RcaAnalysisStatus.PARTIAL
            and not has_incomplete_evidence
        ):
            raise ValueError("partial RCA reports require incomplete evidence sources")
        if (
            self.analysis_status is RcaAnalysisStatus.INSUFFICIENT_EVIDENCE
            and not has_incomplete_evidence
        ):
            raise ValueError(
                "insufficient-evidence reports require incomplete evidence sources"
            )
        return self


class DeterministicRcaAnalyzer(Protocol):
    """Pure future analyzer boundary; implementations must not access backends or networks."""

    def analyze(self, evidence: RcaEvidenceBundle) -> tuple[RcaFinding, ...]:
        """Derive deterministic findings only from the supplied bounded evidence."""

"""Deterministic RCA evidence collection, analysis, and report assembly."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from datetime import datetime, timedelta
from itertools import pairwise
from typing import Final
from uuid import UUID

from industrial_ai_agent.application.rca import (
    DeterministicRcaAnalyzer,
    RcaAnalysisReport,
    RcaAnalysisStatus,
    RcaApprovalEvidence,
    RcaCompleteness,
    RcaComponent,
    RcaConfidence,
    RcaEvidenceBundle,
    RcaEvidenceSource,
    RcaEvidenceSourceStatus,
    RcaFailureEvidence,
    RcaFinding,
    RcaFindingCategory,
    RcaFindingKind,
    RcaLimitationCode,
    RcaLogEvidence,
    RcaMcpToolEvidence,
    RcaMeasurement,
    RcaMeasurementName,
    RcaMeasurementProvenance,
    RcaMeasurementScope,
    RcaMeasurementUnit,
    RcaMetricEvidence,
    RcaOperation,
    RcaOperationStatus,
    RcaRetrievalStage,
    RcaRetrievalStageEvidence,
    RcaRuntimeEvidence,
    RcaSeverity,
    RcaSourceAvailability,
    RcaTimingEvidence,
    RcaTraceSpanEvidence,
)
from industrial_ai_agent.application.rca_evidence import (
    LogRcaEvidencePort,
    MetricRcaEvidencePort,
    RcaEvidenceMissingError,
    RcaEvidenceUnavailableError,
    RcaMetricObservation,
    RcaRunNotAccessibleError,
    RcaRuntimeObservation,
    RcaSpanObservation,
    RcaTraceObservation,
    RuntimeRcaEvidencePort,
    TraceRcaEvidencePort,
)
from industrial_ai_agent.domain.security import SecurityContext

_SOURCE_ORDER: Final = (
    RcaEvidenceSource.RUNTIME,
    RcaEvidenceSource.TEMPO,
    RcaEvidenceSource.LOKI,
    RcaEvidenceSource.PROMETHEUS,
    RcaEvidenceSource.LANGFUSE,
)
_RETRIEVAL_OPERATIONS: Final = {
    RcaOperation.RETRIEVAL_SEARCH: RcaRetrievalStage.SEARCH,
    RcaOperation.RETRIEVAL_EMBEDDING: RcaRetrievalStage.EMBEDDING,
    RcaOperation.RETRIEVAL_LEXICAL: RcaRetrievalStage.LEXICAL,
    RcaOperation.RETRIEVAL_SEMANTIC: RcaRetrievalStage.SEMANTIC,
    RcaOperation.RETRIEVAL_FUSION: RcaRetrievalStage.FUSION,
    RcaOperation.RETRIEVAL_RERANK: RcaRetrievalStage.RERANK,
}
_TIMING_OPERATIONS: Final = frozenset(
    {
        RcaOperation.LLM_CALL,
        RcaOperation.MCP_DISCOVERY,
        RcaOperation.MCP_TOOL,
        RcaOperation.FACTORY_TOOL,
        RcaOperation.KNOWLEDGE_SEARCH,
        *_RETRIEVAL_OPERATIONS,
        RcaOperation.PERSISTENCE_RUN_STORE,
        RcaOperation.APPROVAL_WAIT,
    }
)


class RcaEvidenceCollector:
    """Collect each bounded source independently after the runtime RLS gate succeeds."""

    def __init__(
        self,
        *,
        runtime: RuntimeRcaEvidencePort,
        trace: TraceRcaEvidencePort,
        logs: LogRcaEvidencePort,
        metrics: MetricRcaEvidencePort,
    ) -> None:
        self._runtime = runtime
        self._trace = trace
        self._logs = logs
        self._metrics = metrics

    async def collect(
        self, run_id: UUID, security_context: SecurityContext
    ) -> RcaEvidenceBundle:
        """Return a partial bundle when non-runtime sources fail; runtime access fails closed."""
        runtime = await self._runtime.inspect_run(run_id, security_context)
        if runtime.run_id != run_id:
            raise RcaRunNotAccessibleError(
                "RCA runtime evidence did not match the requested run"
            )
        trajectory = await self._runtime.get_tool_trajectory(run_id, security_context)

        source_status: dict[RcaEvidenceSource, RcaSourceAvailability] = {
            RcaEvidenceSource.RUNTIME: _source_availability(
                RcaEvidenceSource.RUNTIME, RcaEvidenceSourceStatus.AVAILABLE
            ),
            RcaEvidenceSource.LANGFUSE: _source_availability(
                RcaEvidenceSource.LANGFUSE,
                RcaEvidenceSourceStatus.NOT_APPLICABLE,
                RcaLimitationCode.SOURCE_NOT_APPLICABLE,
            ),
        }
        trace: RcaTraceObservation | None = None
        try:
            trace = self._trace.get_run_trace(run_id)
            if trace.spans:
                source_status[RcaEvidenceSource.TEMPO] = _source_availability(
                    RcaEvidenceSource.TEMPO,
                    RcaEvidenceSourceStatus.AVAILABLE,
                    RcaLimitationCode.TRACE_INCOMPLETE if trace.truncated else None,
                )
            else:
                source_status[RcaEvidenceSource.TEMPO] = _source_availability(
                    RcaEvidenceSource.TEMPO,
                    RcaEvidenceSourceStatus.MISSING,
                    RcaLimitationCode.DATA_NOT_RECORDED,
                )
        except Exception as error:  # noqa: BLE001 - preserve source isolation.
            source_status[RcaEvidenceSource.TEMPO] = _source_availability_from_error(
                RcaEvidenceSource.TEMPO, error
            )

        logs = ()
        metrics = ()
        if trace is None:
            source_status[RcaEvidenceSource.LOKI] = _source_availability(
                RcaEvidenceSource.LOKI,
                RcaEvidenceSourceStatus.NOT_APPLICABLE,
                RcaLimitationCode.SOURCE_NOT_APPLICABLE,
            )
            source_status[RcaEvidenceSource.PROMETHEUS] = _source_availability(
                RcaEvidenceSource.PROMETHEUS,
                RcaEvidenceSourceStatus.NOT_APPLICABLE,
                RcaLimitationCode.SOURCE_NOT_APPLICABLE,
            )
        else:
            try:
                logs = self._logs.get_trace_logs(trace)
                source_status[RcaEvidenceSource.LOKI] = _source_availability(
                    RcaEvidenceSource.LOKI,
                    (
                        RcaEvidenceSourceStatus.AVAILABLE
                        if logs
                        else RcaEvidenceSourceStatus.MISSING
                    ),
                    RcaLimitationCode.DATA_NOT_RECORDED if not logs else None,
                )
            except Exception as error:  # noqa: BLE001 - preserve source isolation.
                source_status[RcaEvidenceSource.LOKI] = _source_availability_from_error(
                    RcaEvidenceSource.LOKI, error
                )
            try:
                metrics = self._metrics.get_trace_metrics(trace)
                source_status[RcaEvidenceSource.PROMETHEUS] = _source_availability(
                    RcaEvidenceSource.PROMETHEUS,
                    (
                        RcaEvidenceSourceStatus.AVAILABLE
                        if metrics
                        else RcaEvidenceSourceStatus.MISSING
                    ),
                    RcaLimitationCode.DATA_NOT_RECORDED if not metrics else None,
                )
            except Exception as error:  # noqa: BLE001 - preserve source isolation.
                source_status[RcaEvidenceSource.PROMETHEUS] = (
                    _source_availability_from_error(RcaEvidenceSource.PROMETHEUS, error)
                )

        trace_spans = _trace_spans(trace.spans if trace is not None else ())
        return RcaEvidenceBundle(
            run_id=runtime.run_id,
            trace_id=trace.trace_id if trace is not None else None,
            trace_truncated=trace.truncated if trace is not None else False,
            data_classification=runtime.data_classification,
            source_availability=tuple(
                source_status[source] for source in _SOURCE_ORDER
            ),
            runtime=RcaRuntimeEvidence(
                evidence_ref="EV-RUNTIME-001",
                status=runtime.status,
                run_profile=runtime.run_profile,
                model_profile=runtime.model_profile,
                created_at=runtime.created_at,
                updated_at=runtime.updated_at,
                error_code=runtime.error_code,
                tool_call_count=runtime.tool_call_count,
            ),
            trace_spans=trace_spans,
            mcp_tools=tuple(
                RcaMcpToolEvidence(
                    evidence_ref=f"EV-MCP-{item.sequence:03}",
                    sequence=item.sequence,
                    tool_name=item.tool_name,
                    component=item.component,
                    status=RcaOperationStatus.UNSET,
                )
                for item in trajectory
            ),
            retrieval_stages=_retrieval_stages(trace_spans),
            correlated_logs=tuple(
                RcaLogEvidence(
                    evidence_ref=f"EV-LOG-{index:03}",
                    timestamp=item.timestamp,
                    component=item.component,
                    event_name=item.event_name,
                    severity=item.severity,
                    error_code=item.error_code,
                )
                for index, item in enumerate(logs, start=1)
            ),
            metrics=_metric_evidence(metrics),
            measurements=_run_duration_measurement(trace_spans),
            failures=_failure_evidence(trace_spans),
            approval=RcaApprovalEvidence(
                evidence_ref="EV-APPROVAL-001",
                state=runtime.approval_state,
                requested_at=runtime.approval_requested_at,
                decided_at=runtime.approval_decided_at,
            ),
            persistence_timings=_persistence_timings(trace_spans),
            timings=(*_timing_evidence(trace_spans), *_approval_timing(runtime)),
        )


class DefaultDeterministicRcaAnalyzer:
    """Conservative pure rules over an already bounded RCA evidence bundle."""

    def analyze(self, evidence: RcaEvidenceBundle) -> tuple[RcaFinding, ...]:
        findings: list[RcaFinding] = []
        if evidence.runtime is not None and evidence.runtime.status.value == "failed":
            error_detail = (
                f" (error code: {evidence.runtime.error_code})"
                if evidence.runtime.error_code is not None
                else ""
            )
            findings.append(
                _finding(
                    "RUNTIME",
                    len(findings) + 1,
                    kind=RcaFindingKind.OBSERVED,
                    category_value=RcaFindingCategory.RUN_LIFECYCLE,
                    severity=RcaSeverity.ERROR,
                    component=RcaComponent.AGENT_RUNTIME,
                    statement=f"The persisted run ended with status failed{error_detail}.",
                    confidence=RcaConfidence.HIGH,
                    evidence_refs=(evidence.runtime.evidence_ref,),
                )
            )
        for span in evidence.trace_spans:
            if span.status is not RcaOperationStatus.ERROR:
                continue
            findings.append(
                _finding(
                    "SPAN",
                    len(findings) + 1,
                    kind=RcaFindingKind.OBSERVED,
                    category_value=RcaFindingCategory.FAILURE,
                    severity=RcaSeverity.ERROR,
                    component=span.component,
                    statement=_failed_span_statement(span),
                    confidence=RcaConfidence.HIGH,
                    evidence_refs=(span.evidence_ref,),
                )
            )
            if span.operation is RcaOperation.MCP_DISCOVERY:
                findings.append(
                    _finding(
                        "MCP",
                        len(findings) + 1,
                        kind=RcaFindingKind.DERIVED,
                        category_value=RcaFindingCategory.MCP,
                        severity=RcaSeverity.ERROR,
                        component=RcaComponent.MCP_DISCOVERY,
                        statement="The MCP discovery boundary failed.",
                        confidence=RcaConfidence.HIGH,
                        evidence_refs=(span.evidence_ref,),
                    )
                )
            elif span.operation is RcaOperation.MCP_TOOL:
                findings.append(
                    _finding(
                        "MCP",
                        len(findings) + 1,
                        kind=RcaFindingKind.DERIVED,
                        category_value=RcaFindingCategory.MCP,
                        severity=RcaSeverity.ERROR,
                        component=RcaComponent.MCP,
                        statement="The MCP tool execution boundary failed.",
                        confidence=RcaConfidence.HIGH,
                        evidence_refs=(span.evidence_ref,),
                    )
                )
            elif span.operation in _RETRIEVAL_OPERATIONS:
                findings.append(
                    _finding(
                        "RETRIEVAL",
                        len(findings) + 1,
                        kind=RcaFindingKind.DERIVED,
                        category_value=RcaFindingCategory.RETRIEVAL,
                        severity=RcaSeverity.ERROR,
                        component=RcaComponent.RETRIEVAL,
                        statement=f"The retrieval {span.operation.value} stage failed.",
                        confidence=RcaConfidence.HIGH,
                        evidence_refs=(span.evidence_ref,),
                    )
                )
        findings.extend(_repeated_tool_findings(evidence.mcp_tools, len(findings)))
        findings.extend(
            _source_limitations(evidence.source_availability, len(findings))
        )
        if evidence.trace_truncated:
            findings.append(
                _finding(
                    "TELEMETRY",
                    len(findings) + 1,
                    kind=RcaFindingKind.OBSERVED,
                    category_value=RcaFindingCategory.TELEMETRY,
                    severity=RcaSeverity.WARNING,
                    component=RcaComponent.TELEMETRY,
                    statement="The retrieved trace was truncated and cannot support complete timing analysis.",
                    confidence=RcaConfidence.HIGH,
                    evidence_refs=(
                        _source_reference(evidence, RcaEvidenceSource.TEMPO),
                    ),
                    limitations=(RcaLimitationCode.TRACE_INCOMPLETE,),
                )
            )
        if not evidence.trace_truncated and _source_is_available(
            evidence, RcaEvidenceSource.TEMPO
        ):
            findings.extend(_timing_findings(evidence, len(findings)))
        return tuple(findings)


class RcaAnalysisService:
    """Compose authorized collection and pure deterministic analysis without transport logic."""

    def __init__(
        self, collector: RcaEvidenceCollector, analyzer: DeterministicRcaAnalyzer
    ) -> None:
        self._collector = collector
        self._analyzer = analyzer

    async def analyze(
        self, run_id: UUID, security_context: SecurityContext
    ) -> RcaAnalysisReport:
        evidence = await self._collector.collect(run_id, security_context)
        findings = self._analyzer.analyze(evidence)
        limitations = {
            limitation
            for source in evidence.source_availability
            for limitation in source.limitations
        }
        limitations.add(RcaLimitationCode.NO_PERFORMANCE_BASELINE)
        if evidence.trace_truncated:
            limitations.add(RcaLimitationCode.TRACE_INCOMPLETE)
        incomplete = tuple(
            source.source
            for source in evidence.source_availability
            if source.status
            not in {
                RcaEvidenceSourceStatus.AVAILABLE,
                RcaEvidenceSourceStatus.NOT_APPLICABLE,
            }
        )
        not_applicable = tuple(
            source.source
            for source in evidence.source_availability
            if source.status is RcaEvidenceSourceStatus.NOT_APPLICABLE
        )
        available = tuple(
            source.source
            for source in evidence.source_availability
            if source.status is RcaEvidenceSourceStatus.AVAILABLE
        )
        return RcaAnalysisReport(
            run_id=evidence.run_id,
            trace_id=evidence.trace_id,
            analysis_status=_analysis_status(evidence, incomplete),
            evidence=evidence,
            deterministic_findings=findings,
            overall_limitations=tuple(sorted(limitations, key=str)),
            completeness=RcaCompleteness(
                available_sources=available,
                incomplete_sources=incomplete,
                not_applicable_sources=not_applicable,
            ),
        )


def _source_availability(
    source: RcaEvidenceSource,
    status: RcaEvidenceSourceStatus,
    limitation: RcaLimitationCode | None = None,
) -> RcaSourceAvailability:
    return RcaSourceAvailability(
        evidence_ref=f"EV-SOURCE-{_SOURCE_ORDER.index(source) + 1:03}",
        source=source,
        status=status,
        limitations=(limitation,) if limitation is not None else (),
    )


def _source_availability_from_error(
    source: RcaEvidenceSource,
    error: Exception,
) -> RcaSourceAvailability:
    if isinstance(error, RcaEvidenceUnavailableError):
        return _source_availability(
            source,
            RcaEvidenceSourceStatus.UNAVAILABLE,
            RcaLimitationCode.BACKEND_UNAVAILABLE,
        )
    if isinstance(error, RcaEvidenceMissingError):
        return _source_availability(
            source,
            RcaEvidenceSourceStatus.MISSING,
            RcaLimitationCode.DATA_NOT_RECORDED,
        )
    return _source_availability(
        source,
        RcaEvidenceSourceStatus.MALFORMED,
        RcaLimitationCode.RESPONSE_MALFORMED,
    )


def _trace_spans(
    observations: Iterable[RcaSpanObservation],
) -> tuple[RcaTraceSpanEvidence, ...]:
    return tuple(
        RcaTraceSpanEvidence(
            evidence_ref=f"EV-TRACE-{index:03}",
            span_id=span.span_id,
            parent_span_id=span.parent_span_id,
            operation=span.operation,
            component=span.component,
            service=span.service,
            started_at=span.started_at,
            duration_ms=span.duration_ms,
            status=span.status,
            error_type=span.error_type,
            error_code=span.error_code,
            safe_attributes=span.safe_attributes,
        )
        for index, span in enumerate(observations, start=1)
    )


def _retrieval_stages(
    spans: Iterable[RcaTraceSpanEvidence],
) -> tuple[RcaRetrievalStageEvidence, ...]:
    return tuple(
        RcaRetrievalStageEvidence(
            evidence_ref=f"EV-RETRIEVAL-{index:03}",
            stage=_RETRIEVAL_OPERATIONS[span.operation],
            status=span.status,
            duration_ms=span.duration_ms,
        )
        for index, span in enumerate(
            (span for span in spans if span.operation in _RETRIEVAL_OPERATIONS), start=1
        )
    )


def _metric_evidence(
    observations: Iterable[RcaMetricObservation],
) -> tuple[RcaMetricEvidence, ...]:
    return tuple(
        RcaMetricEvidence(
            evidence_ref=f"EV-METRIC-{index:03}",
            metric_name=metric.metric_name,
            value=metric.value,
            unit=metric.unit,
            window_start=metric.window_start,
            window_end=metric.window_end,
        )
        for index, metric in enumerate(observations, start=1)
    )


def _run_duration_measurement(
    spans: Iterable[RcaTraceSpanEvidence],
) -> tuple[RcaMeasurement, ...]:
    roots = [span for span in spans if span.operation is RcaOperation.AGENT_RUN]
    if not roots:
        return ()
    root = max(roots, key=lambda span: span.duration_ms)
    return (
        RcaMeasurement(
            evidence_ref="EV-MEASUREMENT-001",
            name=RcaMeasurementName.RUN_DURATION_MS,
            value=root.duration_ms,
            unit=RcaMeasurementUnit.MILLISECONDS,
            provenance=RcaMeasurementProvenance.OBSERVED,
            scope=RcaMeasurementScope.RUN,
        ),
    )


def _failure_evidence(
    spans: Iterable[RcaTraceSpanEvidence],
) -> tuple[RcaFailureEvidence, ...]:
    return tuple(
        RcaFailureEvidence(
            evidence_ref=f"EV-FAILURE-{index:03}",
            component=span.component,
            service=span.service,
            operation=span.operation,
            error_type=span.error_type,
            error_code=span.error_code,
        )
        for index, span in enumerate(
            (span for span in spans if span.status is RcaOperationStatus.ERROR), start=1
        )
    )


def _timing_evidence(
    spans: Iterable[RcaTraceSpanEvidence],
) -> tuple[RcaTimingEvidence, ...]:
    return tuple(
        RcaTimingEvidence(
            evidence_ref=f"EV-TIMING-{index:03}",
            operation=span.operation,
            component=span.component,
            started_at=span.started_at,
            duration_ms=span.duration_ms,
        )
        for index, span in enumerate(
            (span for span in spans if span.operation in _TIMING_OPERATIONS), start=1
        )
    )


def _persistence_timings(
    spans: Iterable[RcaTraceSpanEvidence],
) -> tuple[RcaTimingEvidence, ...]:
    return tuple(
        RcaTimingEvidence(
            evidence_ref=f"EV-PERSISTENCE-{index:03}",
            operation=span.operation,
            component=RcaComponent.PERSISTENCE,
            started_at=span.started_at,
            duration_ms=span.duration_ms,
        )
        for index, span in enumerate(
            (
                span
                for span in spans
                if span.operation is RcaOperation.PERSISTENCE_RUN_STORE
            ),
            start=1,
        )
    )


def _approval_timing(
    runtime: RcaRuntimeObservation,
) -> tuple[RcaTimingEvidence, ...]:
    requested_at = runtime.approval_requested_at
    decided_at = runtime.approval_decided_at
    if requested_at is None or decided_at is None or decided_at < requested_at:
        return ()
    return (
        RcaTimingEvidence(
            evidence_ref="EV-APPROVAL-002",
            operation=RcaOperation.APPROVAL_WAIT,
            component=RcaComponent.APPROVAL,
            started_at=requested_at,
            duration_ms=(decided_at - requested_at).total_seconds() * 1_000,
        ),
    )


def _finding(
    category: str,
    index: int,
    *,
    kind: RcaFindingKind,
    category_value: RcaFindingCategory,
    severity: RcaSeverity,
    component: RcaComponent,
    statement: str,
    confidence: RcaConfidence,
    evidence_refs: tuple[str, ...],
    measurements: tuple[RcaMeasurement, ...] = (),
    limitations: tuple[RcaLimitationCode, ...] = (),
) -> RcaFinding:
    return RcaFinding(
        finding_id=f"F-{category}-{index:03}",
        kind=kind,
        category=category_value,
        severity=severity,
        affected_component=component,
        statement=statement,
        confidence=confidence,
        evidence_refs=evidence_refs,
        measurements=measurements,
        limitations=limitations,
    )


def _failed_span_statement(span: RcaTraceSpanEvidence) -> str:
    suffix = f" (error code: {span.error_code})" if span.error_code is not None else ""
    return f"The {span.operation.value} operation recorded an error{suffix}."


def _repeated_tool_findings(
    tools: Iterable[RcaMcpToolEvidence], start_index: int
) -> tuple[RcaFinding, ...]:
    grouped: dict[str, list[RcaMcpToolEvidence]] = defaultdict(list)
    for tool in tools:
        grouped[tool.tool_name].append(tool)
    return tuple(
        _finding(
            "MCP",
            start_index + index,
            kind=RcaFindingKind.DERIVED,
            category_value=RcaFindingCategory.MCP,
            severity=RcaSeverity.WARNING,
            component=items[0].component,
            statement=f"The MCP tool {tool_name} was called {len(items)} times.",
            confidence=RcaConfidence.HIGH,
            evidence_refs=tuple(item.evidence_ref for item in items),
        )
        for index, (tool_name, items) in enumerate(
            sorted(
                (name, entries) for name, entries in grouped.items() if len(entries) > 1
            ),
            start=1,
        )
    )


def _source_limitations(
    sources: Iterable[RcaSourceAvailability], start_index: int
) -> tuple[RcaFinding, ...]:
    limited = (
        source
        for source in sources
        if source.status
        in {
            RcaEvidenceSourceStatus.MISSING,
            RcaEvidenceSourceStatus.UNAVAILABLE,
            RcaEvidenceSourceStatus.MALFORMED,
        }
    )
    return tuple(
        _finding(
            "TELEMETRY",
            start_index + index,
            kind=RcaFindingKind.OBSERVED,
            category_value=RcaFindingCategory.TELEMETRY,
            severity=RcaSeverity.WARNING,
            component=RcaComponent.TELEMETRY,
            statement=f"The {source.source.value} evidence source was {source.status.value}.",
            confidence=RcaConfidence.HIGH,
            evidence_refs=(source.evidence_ref,),
            limitations=source.limitations,
        )
        for index, source in enumerate(limited, start=1)
    )


def _timing_findings(
    evidence: RcaEvidenceBundle, start_index: int
) -> tuple[RcaFinding, ...]:
    root = _run_root(evidence.trace_spans)
    if root is None or root.duration_ms == 0:
        return ()
    contributions = _category_owned_durations(
        evidence.trace_spans, evidence.timings, root
    )
    findings: list[RcaFinding] = []
    for component, duration_ms in sorted(
        contributions.items(), key=lambda item: item[0].value
    ):
        if duration_ms == 0:
            continue
        measurements = (
            RcaMeasurement(
                evidence_ref=root.evidence_ref,
                name=RcaMeasurementName.COMPONENT_DURATION_MS,
                value=duration_ms,
                unit=RcaMeasurementUnit.MILLISECONDS,
                provenance=RcaMeasurementProvenance.DERIVED,
                scope=RcaMeasurementScope.RUN,
            ),
            RcaMeasurement(
                evidence_ref=root.evidence_ref,
                name=RcaMeasurementName.LATENCY_SHARE,
                value=duration_ms / root.duration_ms,
                unit=RcaMeasurementUnit.RATIO,
                provenance=RcaMeasurementProvenance.DERIVED,
                scope=RcaMeasurementScope.RUN,
            ),
        )
        findings.append(
            _finding(
                "LATENCY",
                start_index + len(findings) + 1,
                kind=RcaFindingKind.DERIVED,
                category_value=RcaFindingCategory.LATENCY,
                severity=RcaSeverity.INFO,
                component=component,
                statement=(
                    f"{_component_label(component)} accounted for {duration_ms:.3f} ms "
                    f"({duration_ms / root.duration_ms:.1%}) of analyzed runtime."
                ),
                confidence=RcaConfidence.HIGH,
                evidence_refs=(root.evidence_ref,),
                measurements=measurements,
            )
        )
    if contributions:
        highest = max(contributions.values())
        dominant = [
            component for component, value in contributions.items() if value == highest
        ]
        if highest > 0 and len(dominant) == 1:
            component = dominant[0]
            findings.append(
                _finding(
                    "LATENCY",
                    start_index + len(findings) + 1,
                    kind=RcaFindingKind.DERIVED,
                    category_value=RcaFindingCategory.LATENCY,
                    severity=RcaSeverity.INFO,
                    component=component,
                    statement=(
                        f"{_component_label(component)} execution accounted for the largest "
                        "measured share of analyzed runtime."
                    ),
                    confidence=RcaConfidence.HIGH,
                    evidence_refs=(root.evidence_ref,),
                )
            )
    return tuple(findings)


def _run_root(spans: Iterable[RcaTraceSpanEvidence]) -> RcaTraceSpanEvidence | None:
    roots = [span for span in spans if span.operation is RcaOperation.AGENT_RUN]
    return max(roots, key=lambda span: span.duration_ms) if roots else None


def _category_owned_durations(
    spans: Iterable[RcaTraceSpanEvidence],
    timings: Iterable[RcaTimingEvidence],
    root: RcaTraceSpanEvidence,
) -> dict[RcaComponent, float]:
    """Partition root wall-clock time by priority so nested spans cannot double count.

    Retrieval owns overlapping retrieval intervals before MCP. The remaining categories
    are assigned LLM, persistence, approval, then MCP priority. Any unassigned root time
    remains intentionally unmeasured rather than being attributed speculatively.
    """
    root_start = root.started_at
    root_end = root.started_at + timedelta(milliseconds=root.duration_ms)
    intervals: dict[RcaComponent, list[tuple[datetime, datetime]]] = defaultdict(list)
    for span in spans:
        category = _timing_category(span.operation)
        if category is None:
            continue
        start = max(root_start, span.started_at)
        end = min(root_end, span.started_at + timedelta(milliseconds=span.duration_ms))
        if end > start:
            intervals[category].append((start, end))
    for timing in timings:
        category = _timing_category(timing.operation)
        if category is None or timing.started_at is None:
            continue
        start = max(root_start, timing.started_at)
        end = min(
            root_end, timing.started_at + timedelta(milliseconds=timing.duration_ms)
        )
        if end > start:
            intervals[category].append((start, end))
    boundaries = sorted(
        {
            root_start,
            root_end,
            *(
                point
                for values in intervals.values()
                for interval in values
                for point in interval
            ),
        }
    )
    contributions: dict[RcaComponent, float] = defaultdict(float)
    priority = (
        RcaComponent.RETRIEVAL,
        RcaComponent.LLM,
        RcaComponent.PERSISTENCE,
        RcaComponent.APPROVAL,
        RcaComponent.MCP,
    )
    for start, end in pairwise(boundaries):
        owner = next(
            (
                component
                for component in priority
                if any(
                    interval_start <= start and end <= interval_end
                    for interval_start, interval_end in intervals[component]
                )
            ),
            None,
        )
        if owner is not None:
            contributions[owner] += (end - start).total_seconds() * 1_000
    return dict(contributions)


def _timing_category(operation: RcaOperation) -> RcaComponent | None:
    if operation is RcaOperation.LLM_CALL:
        return RcaComponent.LLM
    if operation in _RETRIEVAL_OPERATIONS:
        return RcaComponent.RETRIEVAL
    if operation is RcaOperation.PERSISTENCE_RUN_STORE:
        return RcaComponent.PERSISTENCE
    if operation is RcaOperation.APPROVAL_WAIT:
        return RcaComponent.APPROVAL
    if operation in {
        RcaOperation.MCP_DISCOVERY,
        RcaOperation.MCP_TOOL,
        RcaOperation.FACTORY_TOOL,
        RcaOperation.KNOWLEDGE_SEARCH,
    }:
        return RcaComponent.MCP
    return None


def _component_label(component: RcaComponent) -> str:
    return {
        RcaComponent.LLM: "LLM",
        RcaComponent.MCP: "MCP",
        RcaComponent.RETRIEVAL: "Retrieval",
        RcaComponent.PERSISTENCE: "Persistence",
        RcaComponent.APPROVAL: "Approval wait",
    }[component]


def _source_reference(evidence: RcaEvidenceBundle, source: RcaEvidenceSource) -> str:
    return next(
        item.evidence_ref
        for item in evidence.source_availability
        if item.source is source
    )


def _source_is_available(
    evidence: RcaEvidenceBundle, source: RcaEvidenceSource
) -> bool:
    return any(
        item.source is source and item.status is RcaEvidenceSourceStatus.AVAILABLE
        for item in evidence.source_availability
    )


def _analysis_status(
    evidence: RcaEvidenceBundle, incomplete: tuple[RcaEvidenceSource, ...]
) -> RcaAnalysisStatus:
    runtime_failure = (
        evidence.runtime is not None and evidence.runtime.status.value == "failed"
    )
    tempo_missing = any(
        source.source is RcaEvidenceSource.TEMPO
        and source.status is RcaEvidenceSourceStatus.MISSING
        for source in evidence.source_availability
    )
    if (
        tempo_missing
        and not evidence.trace_spans
        and not evidence.mcp_tools
        and not runtime_failure
    ):
        return RcaAnalysisStatus.INSUFFICIENT_EVIDENCE
    if incomplete or evidence.trace_truncated:
        return RcaAnalysisStatus.PARTIAL
    return RcaAnalysisStatus.COMPLETE

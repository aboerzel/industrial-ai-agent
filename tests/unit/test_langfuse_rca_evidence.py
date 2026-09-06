import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import UUID

import pytest

from industrial_ai_agent.application.rca import (
    RcaComponent,
    RcaEvidenceSource,
    RcaEvidenceSourceStatus,
    RcaFindingKind,
    RcaMeasurementName,
    RcaMeasurementProvenance,
    RcaOperation,
    RcaOperationStatus,
)
from industrial_ai_agent.application.rca_analysis import (
    DefaultDeterministicRcaAnalyzer,
    RcaAnalysisService,
    RcaEvidenceCollector,
)
from industrial_ai_agent.application.rca_evidence import (
    RcaApprovalState,
    RcaEvidenceMalformedError,
    RcaEvidenceNotAuthorizedError,
    RcaEvidenceUnavailableError,
    RcaLlmTraceObservation,
    RcaRunNotAccessibleError,
    RcaRuntimeObservation,
    RcaSpanObservation,
    RcaTraceObservation,
)
from industrial_ai_agent.domain.security import DataClassification, SecurityContext
from industrial_ai_agent.infrastructure.rca_evidence import LangfuseRcaEvidenceAdapter

RUN_ID = UUID("123e4567-e89b-12d3-a456-426614174000")
TRACE_ID = "0123456789abcdef0123456789abcdef"
NOW = datetime(2026, 9, 6, tzinfo=UTC)
CONTEXT = SecurityContext(
    subject_id="langfuse-rca-test",
    roles=("engineer",),
    clearance=DataClassification.INTERNAL,
    authenticated=True,
)


@dataclass
class _Meta:
    cursor: str | None = None


@dataclass
class _Response:
    data: list[object]
    meta: _Meta


class _LangfuseClient:
    def __init__(self, response: object | Exception) -> None:
        self.response = response
        self.calls: list[dict[str, object]] = []

    def get_many(self, **kwargs: object) -> object:
        self.calls.append(kwargs)
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


def _row(
    *,
    trace_id: str = TRACE_ID,
    input_tokens: int | None = 5,
    output_tokens: int | None = 3,
    total_tokens: int | None = 8,
    cost_status: str = "configured_api_cost",
    total_cost: float | None = 0.0,
    start: datetime = NOW,
    duration_ms: float = 100,
    metadata: dict[str, object] | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        type="GENERATION",
        name="llm.call",
        trace_id=trace_id,
        start_time=start,
        end_time=start + timedelta(milliseconds=duration_ms),
        provided_model_name=None,
        usage_details={
            key: value
            for key, value in {
                "input": input_tokens,
                "output": output_tokens,
                "total": total_tokens,
            }.items()
            if value is not None
        },
        total_cost=total_cost,
        metadata={
            "provider": "ollama",
            "model_profile": "local_quality",
            "attributes.model.name": "qwen3.5:9b",
            "cost_status": cost_status,
            "attributes.cost.api_usd": 0.0,
            **(metadata or {}),
        },
        input="never project prompt text",
        output="never project response text",
    )


def _adapter(
    response: object | Exception, **kwargs: object
) -> tuple[LangfuseRcaEvidenceAdapter, _LangfuseClient]:
    client = _LangfuseClient(response)
    return LangfuseRcaEvidenceAdapter(client, **kwargs), client


def test_adapter_retrieves_only_safe_bounded_generation_projection() -> None:
    adapter, client = _adapter(_Response([_row()], _Meta()))

    result = adapter.get_trace_llm_evidence(
        TRACE_ID, from_time=NOW, to_time=NOW + timedelta(minutes=1)
    )

    generation = result.generations[0]
    assert generation.provider == "ollama"
    assert generation.model_name == "qwen3.5:9b"
    assert generation.input_tokens == 5
    assert generation.duration_ms == 100
    assert "prompt" not in repr(generation)
    assert "response" not in repr(generation)
    assert client.calls[0]["fields"] == "core,basic,model,usage,metadata"
    assert client.calls[0]["limit"] == 50
    assert client.calls[0]["request_options"] == {
        "timeout_in_seconds": 2,
        "max_retries": 0,
    }


def test_adapter_preserves_partial_provider_usage_without_inference() -> None:
    adapter, _ = _adapter(
        _Response([_row(output_tokens=None, total_tokens=None)], _Meta())
    )

    generation = adapter.get_trace_llm_evidence(
        TRACE_ID, from_time=NOW, to_time=NOW
    ).generations[0]

    assert generation.input_tokens == 5
    assert generation.output_tokens is None
    assert generation.total_tokens is None


def test_adapter_supports_multiple_generations_and_marks_bounded_page() -> None:
    adapter, _ = _adapter(
        _Response([_row(), _row(start=NOW + timedelta(seconds=1))], _Meta("next"))
    )

    result = adapter.get_trace_llm_evidence(TRACE_ID, from_time=NOW, to_time=NOW)

    assert len(result.generations) == 2
    assert result.truncated


def test_adapter_maps_timeout_and_backend_authorization_to_safe_errors() -> None:
    timeout, _ = _adapter(TimeoutError("down"))
    denied, _ = _adapter(PermissionError("denied"))

    with pytest.raises(RcaEvidenceUnavailableError):
        timeout.get_trace_llm_evidence(TRACE_ID, from_time=NOW, to_time=NOW)
    with pytest.raises(RcaEvidenceNotAuthorizedError):
        denied.get_trace_llm_evidence(TRACE_ID, from_time=NOW, to_time=NOW)


def test_adapter_rejects_malformed_numbers_and_discards_unrelated_observations() -> (
    None
):
    malformed, _ = _adapter(_Response([_row(input_tokens=-1)], _Meta()))
    unrelated, _ = _adapter(
        _Response(
            [SimpleNamespace(type="TOOL", name="tool.call", trace_id=TRACE_ID)], _Meta()
        )
    )

    with pytest.raises(RcaEvidenceMalformedError):
        malformed.get_trace_llm_evidence(TRACE_ID, from_time=NOW, to_time=NOW)
    assert not unrelated.get_trace_llm_evidence(
        TRACE_ID, from_time=NOW, to_time=NOW
    ).generations


def test_configured_cost_never_becomes_observed_cost() -> None:
    adapter, _ = _adapter(_Response([_row()], _Meta()))

    generation = adapter.get_trace_llm_evidence(
        TRACE_ID, from_time=NOW, to_time=NOW
    ).generations[0]

    assert generation.observed_cost_usd is None
    assert generation.configured_api_cost_usd == 0.0


def test_adapter_keeps_explicit_observed_cost_and_discards_unknown_metadata() -> None:
    adapter, _ = _adapter(
        _Response(
            [
                _row(
                    cost_status="observed_run_cost",
                    total_cost=1.25,
                    metadata={"arbitrary_payload": "never project"},
                )
            ],
            _Meta(),
        )
    )

    generation = adapter.get_trace_llm_evidence(
        TRACE_ID, from_time=NOW, to_time=NOW
    ).generations[0]

    assert generation.observed_cost_usd == 1.25
    assert generation.configured_api_cost_usd is None
    assert "arbitrary_payload" not in repr(generation)
    assert "never project" not in repr(generation)


class _Runtime:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error

    async def inspect_run(
        self, run_id: UUID, security_context: SecurityContext
    ) -> RcaRuntimeObservation:
        if self.error:
            raise self.error
        return RcaRuntimeObservation(
            run_id=run_id,
            status="success",  # type: ignore[arg-type]
            data_classification=DataClassification.INTERNAL,
            run_profile="INTERNAL_DIAGNOSTIC",
            model_profile="troubleshooting",
            created_at=NOW,
            updated_at=NOW + timedelta(seconds=1),
            error_code=None,
            tool_call_count=0,
            approval_state=RcaApprovalState.NONE,
            approval_requested_at=None,
            approval_decided_at=None,
        )

    async def get_tool_trajectory(
        self, run_id: UUID, security_context: SecurityContext
    ) -> tuple[object, ...]:
        return ()


class _Trace:
    def __init__(
        self, span_count: int = 1, timing_offset: timedelta = timedelta()
    ) -> None:
        self.span_count = span_count
        self.timing_offset = timing_offset

    def get_run_trace(self, run_id: UUID) -> RcaTraceObservation:
        return RcaTraceObservation(
            TRACE_ID,
            tuple(
                RcaSpanObservation(
                    span_id=f"{index:016x}",
                    parent_span_id=None,
                    operation=RcaOperation.LLM_CALL,
                    component=RcaComponent.LLM,
                    service=RcaComponent.AGENT_RUNTIME,
                    started_at=NOW + self.timing_offset + timedelta(seconds=index),
                    duration_ms=100,
                    status=RcaOperationStatus.OK,
                    error_type=None,
                    error_code=None,
                )
                for index in range(self.span_count)
            ),
            False,
        )


class _EmptyEvidence:
    def get_trace_logs(self, trace: RcaTraceObservation) -> tuple[object, ...]:
        return ()

    def get_trace_metrics(self, trace: RcaTraceObservation) -> tuple[object, ...]:
        return ()


class _LlmPort:
    def __init__(self, result: RcaLlmTraceObservation | Exception) -> None:
        self.result = result
        self.calls = 0

    def get_trace_llm_evidence(
        self, trace_id: str, *, from_time: datetime, to_time: datetime
    ) -> RcaLlmTraceObservation:
        self.calls += 1
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def _report(
    llm: _LlmPort,
    *,
    runtime: _Runtime | None = None,
    trace: _Trace | None = None,
):
    collector = RcaEvidenceCollector(
        runtime=runtime or _Runtime(),
        trace=trace or _Trace(),
        logs=_EmptyEvidence(),  # type: ignore[arg-type]
        metrics=_EmptyEvidence(),  # type: ignore[arg-type]
        llm=llm,
    )
    return asyncio.run(
        RcaAnalysisService(collector, DefaultDeterministicRcaAnalyzer()).analyze(
            RUN_ID, CONTEXT
        )
    )


def _llm_result(
    *, trace_ok: bool = True, count: int = 1, start: datetime = NOW
) -> RcaLlmTraceObservation:
    adapter, _ = _adapter(
        _Response(
            [_row(start=start + timedelta(seconds=index)) for index in range(count)],
            _Meta(),
        )
    )
    result = adapter.get_trace_llm_evidence(TRACE_ID, from_time=NOW, to_time=NOW)
    return RcaLlmTraceObservation(trace_ok, result.generations, False)


def test_collector_uses_runtime_authorization_before_any_langfuse_call() -> None:
    llm = _LlmPort(_llm_result())

    with pytest.raises(RcaRunNotAccessibleError):
        _report(llm, runtime=_Runtime(RcaRunNotAccessibleError("hidden")))

    assert llm.calls == 0


def test_langfuse_failure_isolated_and_source_status_is_explicit() -> None:
    report = _report(_LlmPort(RcaEvidenceUnavailableError("offline")))

    status = next(
        item.status
        for item in report.evidence.source_availability
        if item.source is RcaEvidenceSource.LANGFUSE
    )
    assert status is RcaEvidenceSourceStatus.UNAVAILABLE
    assert report.evidence.runtime is not None


def test_missing_langfuse_trace_is_explicit_and_does_not_block_the_report() -> None:
    report = _report(_LlmPort(RcaLlmTraceObservation(True, (), False)))

    status = next(
        item.status
        for item in report.evidence.source_availability
        if item.source is RcaEvidenceSource.LANGFUSE
    )
    assert status is RcaEvidenceSourceStatus.MISSING
    assert report.evidence.runtime is not None


def test_langfuse_backend_denial_is_explicit_and_does_not_block_the_report() -> None:
    report = _report(_LlmPort(RcaEvidenceNotAuthorizedError("denied")))

    status = next(
        item.status
        for item in report.evidence.source_availability
        if item.source is RcaEvidenceSource.LANGFUSE
    )
    assert status is RcaEvidenceSourceStatus.NOT_AUTHORIZED
    assert report.evidence.runtime is not None


def test_collector_projects_observed_provenance_and_no_sensitive_payloads() -> None:
    report = _report(_LlmPort(_llm_result()))

    assert any(
        item.name is RcaMeasurementName.INPUT_TOKENS
        and item.provenance is RcaMeasurementProvenance.OBSERVED
        for item in report.evidence.measurements
    )
    assert any(
        item.provenance is RcaMeasurementProvenance.CONFIGURED
        for item in report.evidence.measurements
    )
    serialized = report.model_dump_json()
    for forbidden in ("never project", "tool_arguments", "raw_log", "authorization"):
        assert forbidden not in serialized
    assert all(
        finding.kind
        not in {RcaFindingKind.HYPOTHESIS, RcaFindingKind.CONFIRMED_RUN_CAUSE}
        for finding in report.deterministic_findings
    )


def test_analyzer_reports_generation_count_and_tempo_count_mismatch() -> None:
    report = _report(_LlmPort(_llm_result(count=2)), trace=_Trace(span_count=1))

    assert any(
        "2 LLM generation" in finding.statement
        for finding in report.deterministic_findings
    )
    assert any(
        "different LLM generation counts" in finding.statement
        for finding in report.deterministic_findings
    )


def test_analyzer_reports_timing_mismatch_without_claiming_a_cause() -> None:
    report = _report(
        _LlmPort(_llm_result(start=NOW + timedelta(hours=1))),
        trace=_Trace(timing_offset=timedelta()),
    )

    mismatch = next(
        finding
        for finding in report.deterministic_findings
        if "timings were not plausibly aligned" in finding.statement
    )
    assert mismatch.kind is RcaFindingKind.DERIVED
    assert "cause" not in mismatch.statement.lower()

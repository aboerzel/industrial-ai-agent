"""CERT-01: execution identity survives unrelated reads of a persisted run."""

import asyncio
from base64 import b64encode
from copy import deepcopy
from itertools import permutations
from uuid import UUID

import httpx
import pytest
from test_observability_backends import RUN_ID, TRACE_ID, _tempo_trace_payload
from test_observability_run_visibility import _call, _setup
from test_rca_analysis import CONTEXT, FakeRuntimeEvidence

from industrial_ai_agent.application.rca import (
    RcaEvidenceSource,
    RcaEvidenceSourceStatus,
    RcaOperation,
)
from industrial_ai_agent.application.rca_analysis import (
    DefaultDeterministicRcaAnalyzer,
    RcaAnalysisService,
    RcaEvidenceCollector,
)
from industrial_ai_agent.domain.security import DataClassification
from industrial_ai_agent.infrastructure.observability_backends import (
    LokiAdapter,
    ObservabilityEvidenceService,
    ObservabilityMalformedResponse,
    ObservabilityNotFoundError,
    PrometheusAdapter,
    TempoAdapter,
)
from industrial_ai_agent.infrastructure.rca_evidence import (
    ObservabilityRcaEvidenceAdapter,
)

HISTORY_ID = "5190a7e936a8e28ce5939b17f64a8fd7"


def _payload(operation="agent.run", *, duration_ms=8966.824, run_id=RUN_ID):
    payload = deepcopy(_tempo_trace_payload())
    root = payload["trace"]["resourceSpans"][0]["scopeSpans"][0]["spans"][0]
    root["name"] = operation
    root["endTimeUnixNano"] = str(
        int(root["startTimeUnixNano"]) + int(duration_ms * 1e6)
    )
    root["attributes"] = [{"key": "run.id", "value": {"stringValue": run_id}}]
    children = payload["trace"]["resourceSpans"][1]["scopeSpans"][0]["spans"]
    children.clear()
    if operation == "agent.run":
        for index, (name, start, duration) in enumerate(
            [
                ("llm.call", 10, 3355.216),
                ("mcp.tool", 3370, 10),
                ("llm.call", 3400, 5487.585),
            ]
        ):
            children.append(
                {
                    "spanId": b64encode((index + 20).to_bytes(8, "big")).decode(),
                    "parentSpanId": root["spanId"],
                    "name": name,
                    "startTimeUnixNano": str(
                        int(root["startTimeUnixNano"]) + int(start * 1e6)
                    ),
                    "endTimeUnixNano": str(
                        int(root["startTimeUnixNano"]) + int((start + duration) * 1e6)
                    ),
                    "attributes": [],
                    "status": {},
                }
            )
    return payload


def _adapter(traces, order):
    requests = []

    def handle(request):
        requests.append(request)
        if request.url.path == "/api/search":
            query = request.url.params["q"]
            hits = []
            for trace_id in order:
                resource = traces[trace_id]["trace"]["resourceSpans"][0]
                span = resource["scopeSpans"][0]["spans"][0]
                attributes = {
                    a["key"]: a["value"]["stringValue"] for a in span["attributes"]
                }
                if f'"{attributes["run.id"]}"' not in query:
                    continue
                if 'name = "agent.run"' in query and span["name"] != "agent.run":
                    continue
                if (
                    'resource.service.name = "industrial-ai-agent"' in query
                    and resource["resource"]["attributes"][0]["value"]["stringValue"]
                    != "industrial-ai-agent"
                ):
                    continue
                hits.append({"traceID": trace_id})
            return httpx.Response(
                200, json={"traces": hits[: int(request.url.params["limit"])]}
            )
        return httpx.Response(200, json=traces[request.url.path.rsplit("/", 1)[-1]])

    client = httpx.Client(transport=httpx.MockTransport(handle))
    return TempoAdapter("http://tempo", client=client), requests


@pytest.mark.parametrize("history_count", [1, 3], ids=["CERT01-02", "CERT01-03"])
def test_history_reads_do_not_displace_execution(history_count):
    traces = {TRACE_ID: _payload()}
    reads = [f"{index + 30:032x}" for index in range(history_count)]
    traces.update(
        {tid: _payload("GET investigation history", duration_ms=7.469) for tid in reads}
    )
    adapter, requests = _adapter(traces, [*reads, TRACE_ID])
    trace = adapter.get_run_trace(RUN_ID)
    assert trace.trace_id == TRACE_ID
    assert len(trace.spans) == 4
    assert requests[0].url.params["limit"] == "2"


def test_cert01_01_exact_certification_reproduction():
    adapter, _ = _adapter(
        {
            TRACE_ID: _payload(),
            HISTORY_ID: _payload("GET investigation history", duration_ms=7.469),
        },
        [HISTORY_ID, TRACE_ID],
    )
    trace = adapter.get_run_trace(RUN_ID)
    assert trace.trace_id == TRACE_ID
    assert trace.duration_ms == pytest.approx(8966.824)


@pytest.mark.parametrize("order", list(permutations([TRACE_ID, HISTORY_ID, "a" * 32])))
def test_cert01_04_backend_order_is_irrelevant(order):
    adapter, _ = _adapter(
        {
            TRACE_ID: _payload(),
            HISTORY_ID: _payload("GET history"),
            "a" * 32: _payload("rca.analysis"),
        },
        order,
    )
    assert adapter.get_run_trace(RUN_ID).trace_id == TRACE_ID


def test_cert01_05_execution_keeps_actual_llm_and_tool_evidence():
    adapter, _ = _adapter({TRACE_ID: _payload()}, [TRACE_ID])
    trace = adapter.get_run_trace(RUN_ID)
    assert sum(s.operation_name == "llm.call" for s in trace.spans) == 2
    assert sum(s.operation_name == "mcp.tool" for s in trace.spans) == 1


def test_cert01_06_short_execution_wins_over_longer_read():
    execution = _payload(duration_ms=1)
    execution["trace"]["resourceSpans"][1]["scopeSpans"][0]["spans"].clear()
    adapter, _ = _adapter(
        {TRACE_ID: execution, HISTORY_ID: _payload("GET history", duration_ms=90000)},
        [HISTORY_ID, TRACE_ID],
    )
    trace = adapter.get_run_trace(RUN_ID)
    assert trace.trace_id == TRACE_ID
    assert trace.duration_ms == 1


def test_cert01_07_missing_execution_has_no_history_fallback():
    adapter, _ = _adapter({HISTORY_ID: _payload("GET history")}, [HISTORY_ID])
    with pytest.raises(ObservabilityNotFoundError):
        adapter.get_run_trace(RUN_ID)


def test_cert01_08_hidden_run_is_denied_before_trace_lookup():
    servers, backend, context, _, _ = _setup(DataClassification.PUBLIC)
    with pytest.raises(LookupError, match="^Agent run was not found$"):
        asyncio.run(
            _call(
                servers["observability"], "get_run_trace", {"run_id": RUN_ID}, context
            )
        )
    assert backend.calls == []


@pytest.mark.parametrize("execution_available", [True, False])
def test_cert01_09_real_rca_report_uses_execution_evidence(execution_available):
    tempo, _ = _adapter(
        {TRACE_ID: _payload(), HISTORY_ID: _payload("GET history")},
        [HISTORY_ID, TRACE_ID] if execution_available else [HISTORY_ID],
    )
    empty = httpx.Client(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(
                200, json={"status": "success", "data": {"result": []}}
            )
        )
    )
    service = ObservabilityEvidenceService(
        tempo=tempo,
        loki=LokiAdapter("http://loki", client=empty),
        prometheus=PrometheusAdapter("http://prometheus", client=empty),
    )
    evidence = ObservabilityRcaEvidenceAdapter(service)
    report = asyncio.run(
        RcaAnalysisService(
            RcaEvidenceCollector(
                runtime=FakeRuntimeEvidence(),
                trace=evidence,
                logs=evidence,
                metrics=evidence,
            ),
            DefaultDeterministicRcaAnalyzer(),
        ).analyze(UUID(RUN_ID), CONTEXT)
    )
    bundle = report.evidence
    tempo_status = next(
        s.status
        for s in bundle.source_availability
        if s.source == RcaEvidenceSource.TEMPO
    )
    if not execution_available:
        assert report.trace_id is None
        assert tempo_status == RcaEvidenceSourceStatus.MISSING
        assert bundle.trace_spans == ()
        return
    assert tempo_status == RcaEvidenceSourceStatus.AVAILABLE
    assert bundle.trace_id == TRACE_ID
    assert sum(s.operation == RcaOperation.LLM_CALL for s in bundle.trace_spans) == 2
    assert any(s.operation == RcaOperation.MCP_TOOL for s in bundle.trace_spans)


def test_cert01_10_continuation_has_own_run_and_resume_is_not_initial_execution():
    next_run = "123e4567-e89b-12d3-a456-426614174001"
    next_trace = "b" * 32
    traces = {
        TRACE_ID: _payload(),
        HISTORY_ID: _payload("approval.resume"),
        next_trace: _payload(run_id=next_run),
    }
    adapter, _ = _adapter(traces, [next_trace, HISTORY_ID, TRACE_ID])
    assert adapter.get_run_trace(RUN_ID).trace_id == TRACE_ID
    assert adapter.get_run_trace(next_run).trace_id == next_trace


def test_distinct_duplicate_execution_traces_fail_closed_in_any_order():
    for order in [(TRACE_ID, HISTORY_ID), (HISTORY_ID, TRACE_ID)]:
        adapter, _ = _adapter({TRACE_ID: _payload(), HISTORY_ID: _payload()}, order)
        with pytest.raises(ObservabilityMalformedResponse, match="ambiguous"):
            adapter.get_run_trace(RUN_ID)


def test_duplicate_backend_row_for_same_trace_is_not_ambiguous():
    adapter, _ = _adapter({TRACE_ID: _payload()}, [TRACE_ID, TRACE_ID])
    assert adapter.get_run_trace(RUN_ID).trace_id == TRACE_ID


def test_misbound_backend_trace_is_rejected():
    def handle(request):
        return httpx.Response(
            200,
            json={"traces": [{"traceID": HISTORY_ID}]}
            if request.url.path == "/api/search"
            else _payload("GET history"),
        )

    adapter = TempoAdapter(
        "http://tempo", client=httpx.Client(transport=httpx.MockTransport(handle))
    )
    with pytest.raises(ObservabilityNotFoundError):
        adapter.get_run_trace(RUN_ID)

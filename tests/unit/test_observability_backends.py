from __future__ import annotations

from datetime import UTC, datetime, timedelta

import httpx
import pytest

from industrial_ai_agent.infrastructure.observability_backends import (
    MAX_LOG_EVENTS,
    MAX_LOOKBACK,
    MAX_METRIC_POINTS,
    MAX_TRACE_SPANS,
    InvalidObservabilityIdentifier,
    LokiAdapter,
    ObservabilityBackendUnavailable,
    ObservabilityEvidenceService,
    ObservabilityMalformedResponse,
    ObservabilityNotFoundError,
    PrometheusAdapter,
    TempoAdapter,
)

RUN_ID = "123e4567-e89b-12d3-a456-426614174000"
TRACE_ID = "0123456789abcdef0123456789abcdef"


def test_run_id_lookup_uses_fixed_traceql_and_returns_safe_trace() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/api/search":
            return _json_response({"traces": [{"traceID": TRACE_ID}]})
        return _json_response(_tempo_trace_payload())

    trace = TempoAdapter("http://tempo", client=_client(handler)).get_run_trace(RUN_ID)

    assert trace.run_id == RUN_ID
    assert trace.trace_id == TRACE_ID
    assert [span.operation_name for span in trace.spans] == [
        "agent.run",
        "mcp.discovery",
    ]
    assert requests[0].url.params["q"] == f'{{ span.run.id = "{RUN_ID}" }}'
    assert requests[0].url.params["limit"] == "1"


def test_trace_parsing_orders_parent_before_child_and_removes_sensitive_attributes() -> (
    None
):
    trace = TempoAdapter(
        "http://tempo", client=_client(lambda _: _json_response(_tempo_trace_payload()))
    ).get_trace(TRACE_ID)

    root, child = trace.spans
    assert root.span_id == "0102030405060708"
    assert child.parent_span_id == root.span_id
    assert root.attributes == {"run.id": RUN_ID, "operation.status": "success"}
    assert child.attributes == {
        "error.code": "McpUnavailable",
        "operation.status": "failure",
    }
    assert child.error_code == "McpUnavailable"


def test_trace_and_run_identifier_validation_rejects_invalid_values() -> None:
    adapter = TempoAdapter("http://tempo", client=_client(lambda _: _json_response({})))

    with pytest.raises(InvalidObservabilityIdentifier):
        adapter.get_trace("arbitrary TraceQL")
    with pytest.raises(InvalidObservabilityIdentifier):
        adapter.get_run_trace("not-a-uuid")


def test_trace_not_found_and_backend_unavailable_are_typed() -> None:
    missing = TempoAdapter(
        "http://tempo", client=_client(lambda _: _json_response({"traces": []}))
    )
    unavailable = TempoAdapter(
        "http://tempo", client=_client(lambda _: httpx.Response(503))
    )

    with pytest.raises(ObservabilityNotFoundError):
        missing.get_run_trace(RUN_ID)
    with pytest.raises(ObservabilityBackendUnavailable):
        unavailable.get_trace(TRACE_ID)


def test_loki_trace_correlation_projects_only_safe_metadata_and_bounds_results() -> (
    None
):
    values = [
        [str(1_700_000_000_000_000_000 + index), "must never escape"]
        for index in range(MAX_LOG_EVENTS + 10)
    ]
    payload = {
        "status": "success",
        "data": {
            "result": [
                {
                    "stream": {
                        "trace_id": TRACE_ID,
                        "span_id": "0123456789abcdef",
                        "run_id": RUN_ID,
                        "service_name": "factory-mcp",
                        "event_name": "mcp.server.failed",
                        "severity_text": "ERROR",
                        "error_code": "McpUnavailable",
                        "authorization": "must-not-escape",
                    },
                    "values": values,
                }
            ]
        },
    }
    events = LokiAdapter(
        "http://loki", client=_client(lambda _: _json_response(payload))
    ).get_trace_logs(
        TRACE_ID,
        start_time=datetime.now(UTC) - timedelta(minutes=1),
        end_time=datetime.now(UTC),
    )

    assert len(events) == MAX_LOG_EVENTS
    assert events[0].model_dump() == {
        "timestamp": datetime.fromtimestamp(1_700_000_000, UTC),
        "service_name": "factory-mcp",
        "event_name": "mcp.server.failed",
        "severity": "ERROR",
        "trace_id": TRACE_ID,
        "span_id": "0123456789abcdef",
        "run_id": RUN_ID,
        "error_code": "McpUnavailable",
    }


def test_loki_rejects_invalid_trace_id_and_unavailable_or_malformed_responses() -> None:
    now = datetime.now(UTC)
    adapter = LokiAdapter("http://loki", client=_client(lambda _: httpx.Response(503)))
    with pytest.raises(InvalidObservabilityIdentifier):
        adapter.get_trace_logs(
            "not-a-trace", start_time=now - timedelta(seconds=1), end_time=now
        )
    with pytest.raises(ObservabilityBackendUnavailable):
        adapter.get_trace_logs(
            TRACE_ID, start_time=now - timedelta(seconds=1), end_time=now
        )
    malformed = LokiAdapter(
        "http://loki",
        client=_client(lambda _: _json_response({"status": "success", "data": {}})),
    )
    with pytest.raises(ObservabilityMalformedResponse):
        malformed.get_trace_logs(
            TRACE_ID, start_time=now - timedelta(seconds=1), end_time=now
        )


def test_prometheus_constructs_bounded_queries_and_bounds_points() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return _json_response(
            {
                "status": "success",
                "data": {
                    "resultType": "matrix",
                    "result": [
                        {
                            "values": [
                                [str(1_700_000_000 + index), "1"]
                                for index in range(MAX_METRIC_POINTS + 10)
                            ]
                        }
                    ],
                },
            }
        )

    context = PrometheusAdapter(
        "http://prometheus", client=_client(handler)
    ).service_health("factory-mcp", "5m")

    assert len(context.series) == 7
    assert all(len(series.points) == MAX_METRIC_POINTS for series in context.series)
    assert all("factory-mcp" in request.url.params["query"] for request in requests)
    assert all("arbitrary" not in request.url.params["query"] for request in requests)
    assert all(request.url.path == "/api/v1/query_range" for request in requests)


def test_prometheus_rejects_unrepresentable_window_and_backend_failures() -> None:
    adapter = PrometheusAdapter(
        "http://prometheus", client=_client(lambda _: httpx.Response(503))
    )
    with pytest.raises(InvalidObservabilityIdentifier):
        adapter.service_health("factory-mcp", "arbitrary PromQL")
    with pytest.raises(ObservabilityBackendUnavailable):
        adapter.service_health("factory-mcp", "5m")


def test_run_metrics_resolves_equivalent_context_for_run_and_trace_identifiers() -> (
    None
):
    tempo = TempoAdapter("http://tempo", client=_client(_tempo_handler))
    prometheus = PrometheusAdapter(
        "http://prometheus", client=_client(_prometheus_handler)
    )
    service = ObservabilityEvidenceService(
        tempo=tempo,
        loki=LokiAdapter(
            "http://loki",
            client=_client(
                lambda _: _json_response({"status": "success", "data": {"result": []}})
            ),
        ),
        prometheus=prometheus,
    )

    from_run_id = service.get_run_metrics(RUN_ID)
    from_trace_id = service.get_run_metrics(TRACE_ID)

    assert from_run_id == from_trace_id
    assert from_run_id.source == "trace_correlated_window"


@pytest.mark.parametrize("identifier", (RUN_ID, TRACE_ID))
def test_run_metrics_returns_neutral_not_found_for_unknown_valid_identifier(
    identifier: str,
) -> None:
    tempo = TempoAdapter(
        "http://tempo",
        client=_client(_unknown_tempo_handler),
    )
    service = ObservabilityEvidenceService(
        tempo=tempo,
        loki=LokiAdapter(
            "http://loki",
            client=_client(
                lambda _: _json_response({"status": "success", "data": {"result": []}})
            ),
        ),
        prometheus=PrometheusAdapter(
            "http://prometheus", client=_client(_prometheus_handler)
        ),
    )

    with pytest.raises(ObservabilityNotFoundError):
        service.get_run_metrics(identifier)


def test_run_metrics_rejects_malformed_identifier() -> None:
    service = ObservabilityEvidenceService(
        tempo=TempoAdapter(
            "http://tempo", client=_client(lambda _: _json_response({}))
        ),
        loki=LokiAdapter(
            "http://loki",
            client=_client(
                lambda _: _json_response({"status": "success", "data": {"result": []}})
            ),
        ),
        prometheus=PrometheusAdapter(
            "http://prometheus", client=_client(_prometheus_handler)
        ),
    )

    with pytest.raises(InvalidObservabilityIdentifier):
        service.get_run_metrics("not-an-identifier")


def test_lookback_and_trace_result_bounds_are_enforced() -> None:
    now = datetime.now(UTC)
    loki = LokiAdapter("http://loki", client=_client(lambda _: _json_response({})))
    with pytest.raises(InvalidObservabilityIdentifier):
        loki.get_trace_logs(
            TRACE_ID, start_time=now - MAX_LOOKBACK - timedelta(seconds=1), end_time=now
        )

    payload = _tempo_trace_payload(span_count=MAX_TRACE_SPANS + 1)
    trace = TempoAdapter(
        "http://tempo", client=_client(lambda _: _json_response(payload))
    ).get_trace(TRACE_ID)
    assert len(trace.spans) == MAX_TRACE_SPANS
    assert trace.truncated is True


def test_investigation_aggregates_evidence_without_claiming_root_cause() -> None:
    tempo = TempoAdapter("http://tempo", client=_client(_tempo_handler))
    loki = LokiAdapter(
        "http://loki",
        client=_client(
            lambda _: _json_response({"status": "success", "data": {"result": []}})
        ),
    )
    prometheus = PrometheusAdapter(
        "http://prometheus", client=_client(_prometheus_handler)
    )
    result = ObservabilityEvidenceService(
        tempo=tempo, loki=loki, prometheus=prometheus
    ).investigate_run(RUN_ID)

    assert result["failing_service"] == "factory-mcp"
    assert result["failing_operation"] == "mcp.discovery"
    assert result["error_code"] == "McpUnavailable"
    assert "not a root-cause conclusion" in result["limitations"][0]


def _tempo_handler(request: httpx.Request) -> httpx.Response:
    if request.url.path == "/api/search":
        return _json_response({"traces": [{"traceID": TRACE_ID}]})
    return _json_response(_tempo_trace_payload())


def _unknown_tempo_handler(request: httpx.Request) -> httpx.Response:
    if request.url.path == "/api/search":
        return _json_response({"traces": []})
    return httpx.Response(404)


def _prometheus_handler(_: httpx.Request) -> httpx.Response:
    return _json_response(
        {
            "status": "success",
            "data": {
                "resultType": "matrix",
                "result": [{"values": [["1700000000", "0"]]}],
            },
        }
    )


def _tempo_trace_payload(span_count: int = 2) -> dict[str, object]:
    spans = [
        {
            "spanId": "AQIDBAUGBwg=",
            "name": "agent.run",
            "startTimeUnixNano": "1700000000000000000",
            "endTimeUnixNano": "1700000001000000000",
            "attributes": [
                {"key": "run.id", "value": {"stringValue": RUN_ID}},
                {"key": "prompt", "value": {"stringValue": "secret prompt"}},
                {"key": "operation.status", "value": {"stringValue": "success"}},
            ],
            "status": {},
        },
        {
            "spanId": "CQoLDA0ODxA=",
            "parentSpanId": "AQIDBAUGBwg=",
            "name": "mcp.discovery",
            "startTimeUnixNano": "1700000000100000000",
            "endTimeUnixNano": "1700000000200000000",
            "attributes": [
                {"key": "error.code", "value": {"stringValue": "McpUnavailable"}},
                {"key": "authorization", "value": {"stringValue": "secret"}},
                {"key": "operation.status", "value": {"stringValue": "failure"}},
            ],
            "status": {"code": "STATUS_CODE_ERROR"},
        },
    ]
    for index in range(2, span_count):
        spans.append(
            {
                "spanId": (index.to_bytes(8, "big")).hex(),
                "name": "agent.run",
                "startTimeUnixNano": str(1700000000000000000 + index),
                "endTimeUnixNano": str(1700000000000000001 + index),
                "attributes": [],
                "status": {},
            }
        )
    return {
        "trace": {
            "resourceSpans": [
                {
                    "resource": {
                        "attributes": [
                            {
                                "key": "service.name",
                                "value": {"stringValue": "industrial-ai-agent"},
                            }
                        ]
                    },
                    "scopeSpans": [{"spans": [spans[0], *spans[2:]]}],
                },
                {
                    "resource": {
                        "attributes": [
                            {
                                "key": "service.name",
                                "value": {"stringValue": "factory-mcp"},
                            }
                        ]
                    },
                    "scopeSpans": [{"spans": [spans[1]]}],
                },
            ]
        }
    }


def _client(handler):
    return httpx.Client(transport=httpx.MockTransport(handler), base_url="http://test")


def _json_response(payload: object) -> httpx.Response:
    return httpx.Response(200, json=payload)

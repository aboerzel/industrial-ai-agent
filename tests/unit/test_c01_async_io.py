"""Event-controlled regressions for synchronous RCA evidence and document I/O."""

import asyncio
from contextvars import ContextVar
from threading import Event, Thread, get_ident

import httpx
import pytest
from opentelemetry import context as otel_context
from test_fastapi_api import (
    FakeDocumentContentReader,
    FakeRunService,
    _confidential_request,
    _success_result,
    create_app,
)
from test_rca_analysis import (
    CONTEXT,
    RUN_ID,
    FakeLogEvidence,
    FakeMetricEvidence,
    FakeRuntimeEvidence,
    FakeTraceEvidence,
)
from test_rca_reasoning import (
    _FixedZoneResolver,
    _profile,
    _RecordingClient,
    _report,
    _resolver,
    _valid_output,
)

from industrial_ai_agent.agent.agent_run import DocumentReference
from industrial_ai_agent.agent.model_egress import (
    EgressCheckedLLMClient,
    ExecutionZone,
    ModelExecutionAuthorizer,
)
from industrial_ai_agent.application.rca_analysis import (
    DefaultDeterministicRcaAnalyzer,
    RcaAnalysisService,
    RcaEvidenceCollector,
)
from industrial_ai_agent.application.rca_evidence import RcaLlmTraceObservation
from industrial_ai_agent.application.rca_reasoning import LlmRcaReasoner
from industrial_ai_agent.domain.security import DataClassification
from industrial_ai_agent.infrastructure.rca_mcp_server import create_rca_mcp_server

_REQUEST_CONTEXT = ContextVar("c01_request_context", default=None)


class _Gate:
    """Release on explicit progress; the watchdog only prevents a broken test hanging."""

    def __init__(self) -> None:
        self.started = Event()
        self.progress = Event()
        self.release = Event()
        self.finished = Event()
        self.thread_id = None
        self.context = None
        self.trace_context = None
        self.calls = 0

    def block(self) -> None:
        self.calls += 1
        self.thread_id = get_ident()
        self.context = _REQUEST_CONTEXT.get()
        self.trace_context = otel_context.get_value("c01-trace")
        self.started.set()
        if not self.release.wait(5):
            raise TimeoutError("Synthetic I/O watchdog expired")

    def watchdog(self) -> None:
        self.started.wait(5)
        self.progress.wait(1)
        self.release.set()


class _LlmEvidence:
    def get_trace_llm_evidence(self, trace_id, *, from_time, to_time):
        return RcaLlmTraceObservation(
            trace_id_consistent=True, generations=(), truncated=False
        )


def _service(*, blocked_source=None, gate=None, monkeypatch=None):
    ports = {
        "trace": (FakeTraceEvidence(), "get_run_trace"),
        "logs": (FakeLogEvidence(), "get_trace_logs"),
        "metrics": (FakeMetricEvidence(), "get_trace_metrics"),
        "llm": (_LlmEvidence(), "get_trace_llm_evidence"),
    }
    if blocked_source is not None:
        port, method = ports[blocked_source]
        original = getattr(port, method)

        def blocked(*args, **kwargs):
            try:
                gate.block()
                return original(*args, **kwargs)
            finally:
                gate.finished.set()

        monkeypatch.setattr(port, method, blocked)
    return RcaAnalysisService(
        RcaEvidenceCollector(
            runtime=FakeRuntimeEvidence(),
            **{key: value[0] for key, value in ports.items()},
        ),
        DefaultDeterministicRcaAnalyzer(),
    )


async def _while_blocked(operation, gate, unrelated):
    loop_thread = get_ident()
    watchdog = Thread(target=gate.watchdog, name="c01-test-watchdog")
    watchdog.start()
    task = asyncio.create_task(operation)
    try:
        assert await asyncio.to_thread(gate.started.wait, 3)
        result = await asyncio.wait_for(unrelated(), timeout=0.5)
        # This proves progress while I/O is pending, rather than measuring a sleep.
        assert not gate.release.is_set()
        assert not task.done()
        assert gate.thread_id != loop_thread
        gate.progress.set()
        return result
    finally:
        gate.release.set()
        await asyncio.gather(task, return_exceptions=True)
        gate.progress.set()
        await asyncio.to_thread(watchdog.join, 3)
        assert not watchdog.is_alive()
        assert gate.finished.is_set()


@pytest.mark.parametrize("source", ["trace", "logs", "metrics", "llm"])
def test_evidence_io_preserves_event_loop_progress_context_and_report(
    source, monkeypatch
):
    gate = _Gate()
    service = _service(blocked_source=source, gate=gate, monkeypatch=monkeypatch)

    async def run():
        token = _REQUEST_CONTEXT.set("trusted-request")
        trace_token = otel_context.attach(
            otel_context.set_value("c01-trace", "synthetic-trace")
        )
        try:
            baseline = await _service().analyze(RUN_ID, CONTEXT)
            reports = []

            async def collect():
                reports.append(await service.analyze(RUN_ID, CONTEXT))

            await _while_blocked(
                collect(), gate, lambda: _service().analyze(RUN_ID, CONTEXT)
            )
            assert reports == [baseline]
        finally:
            otel_context.detach(trace_token)
            _REQUEST_CONTEXT.reset(token)

    asyncio.run(run())
    assert gate.context == "trusted-request"
    assert gate.trace_context == "synthetic-trace"
    assert gate.calls == 1


class _DocumentReader(FakeDocumentContentReader):
    def __init__(self, gate):
        super().__init__()
        self.gate = gate
        self.blocked = False

    def get_document(self, document_id, security_context):
        if not self.blocked:
            return super().get_document(document_id, security_context)
        try:
            self.gate.block()
            return super().get_document(document_id, security_context)
        finally:
            self.gate.finished.set()


@pytest.mark.parametrize(
    "route", ["open", "download", "create", "run", "investigation", "pdf"]
)
def test_document_io_all_publication_paths_allow_health_progress(route):
    gate = _Gate()
    reader = _DocumentReader(gate)
    result = _success_result().model_copy(
        update={
            "documents": (
                DocumentReference(
                    document_id="doc-quality-procedure",
                    title="Synthetic procedure",
                    format="markdown",
                ),
            )
        }
    )
    app = create_app(FakeRunService(result=result), document_content_reader=reader)

    async def run():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://fixture"
        ) as client:
            created = await client.post("/api/v1/runs", json=_confidential_request())
            assert created.status_code == 200
            data = created.json()
            urls = {
                "open": "/api/v1/documents/doc-quality-procedure",
                "download": "/api/v1/documents/doc-quality-procedure/download",
                "run": f"/api/v1/runs/{data['run_id']}",
                "investigation": f"/api/v1/investigations/{data['investigation_id']}",
                "pdf": f"/api/v1/investigations/{data['investigation_id']}/pdf",
            }
            reader.blocked = True
            responses = []

            async def request():
                response = (
                    await client.post("/api/v1/runs", json=_confidential_request())
                    if route == "create"
                    else await client.get(
                        urls[route], params={"user_clearance": "CONFIDENTIAL"}
                    )
                )
                responses.append(response)

            health = await _while_blocked(
                request(), gate, lambda: client.get("/health")
            )
            assert health.status_code == 200
            assert [response.status_code for response in responses] == [200]
            assert reader.contexts[-1][1].clearance == DataClassification.CONFIDENTIAL

    asyncio.run(run())
    assert gate.calls == 1


def test_cancelling_evidence_io_does_not_publish_or_continue_collection(monkeypatch):
    gate = _Gate()
    service = _service(blocked_source="trace", gate=gate, monkeypatch=monkeypatch)
    errors = []
    published = []

    async def run():
        loop = asyncio.get_running_loop()
        loop.set_exception_handler(lambda _loop, event: errors.append(event))

        async def request():
            published.append(await service.analyze(RUN_ID, CONTEXT))

        task = asyncio.create_task(request())
        try:
            assert await asyncio.to_thread(gate.started.wait, 3)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(task, timeout=0.5)
            assert not gate.release.is_set()
            assert not published
            assert (await _service().analyze(RUN_ID, CONTEXT)).run_id == RUN_ID
        finally:
            gate.release.set()
            await asyncio.gather(task, return_exceptions=True)
            await loop.shutdown_default_executor()
        assert gate.finished.is_set()
        assert not [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]

    asyncio.run(run())
    assert not errors
    assert not published


def test_mcp_evidence_io_does_not_serialize_independent_rca_requests(monkeypatch):
    gate = _Gate()
    blocked = _service(blocked_source="trace", gate=gate, monkeypatch=monkeypatch)
    blocked_server = create_rca_mcp_server(analysis_service=blocked)
    independent_server = create_rca_mcp_server(analysis_service=_service())

    async def run():
        result = await _while_blocked(
            blocked_server.call_tool("analyze_run", {"run_id": str(RUN_ID)}),
            gate,
            lambda: independent_server.call_tool(
                "analyze_run", {"run_id": str(RUN_ID)}
            ),
        )
        assert result.structured_content["run_id"] == str(RUN_ID)

    asyncio.run(run())


class _Provider(_RecordingClient):
    def __init__(self, gate=None, error=None):
        super().__init__(_valid_output())
        self.gate = gate
        self.error = error

    def chat(self, model_id, request):
        try:
            if self.gate is not None:
                self.gate.block()
            if self.error is not None:
                raise self.error
            return super().chat(model_id, request)
        finally:
            if self.gate is not None:
                self.gate.finished.set()


def _reasoning_server(
    provider,
    *,
    timeout=2,
    zone=ExecutionZone.LOCAL,
    classification=DataClassification.INTERNAL,
):
    metadata = []
    authorizations = []

    class Analysis:
        async def analyze(self, run_id, security_context):
            assert security_context.authenticated
            return _report(classification=classification)

    class Authorization:
        def require_allowed(self, classification, execution_zone, max_classification):
            authorizations.append((classification, execution_zone))
            ModelExecutionAuthorizer().require_allowed(
                classification, execution_zone, max_classification
            )

    def client_factory(classification, focus):
        metadata.append((classification, _REQUEST_CONTEXT.get()))
        return EgressCheckedLLMClient(
            provider,
            _FixedZoneResolver(zone),
            classification,
            authorizer=Authorization(),
        )

    reasoner = LlmRcaReasoner(
        model_resolver=_resolver(
            _profile("local", ExecutionZone.LOCAL), classification
        ),
        client_factory=client_factory,
        timeout_seconds=timeout,
    )
    return (
        create_rca_mcp_server(analysis_service=Analysis(), reasoner=reasoner),
        metadata,
        authorizations,
    )


def test_optional_provider_progress_success_context_and_egress_remain_intact():
    gate = _Gate()
    provider = _Provider(gate)
    server, metadata, authorizations = _reasoning_server(provider)

    async def run():
        token = _REQUEST_CONTEXT.set("trusted-request")
        try:
            responses = []

            async def explain():
                responses.append(
                    await server.call_tool(
                        "analyze_run", {"run_id": str(RUN_ID), "reasoning": "explain"}
                    )
                )

            baseline = await _while_blocked(
                explain(),
                gate,
                lambda: server.call_tool("analyze_run", {"run_id": str(RUN_ID)}),
            )
            explained = responses[0].structured_content
            assert explained["reasoning"]["status"] == "available"
            assert {k: v for k, v in explained.items() if k != "reasoning"} == {
                k: v for k, v in baseline.structured_content.items() if k != "reasoning"
            }
        finally:
            _REQUEST_CONTEXT.reset(token)

    asyncio.run(run())
    assert metadata == [(DataClassification.INTERNAL, "trusted-request")]
    assert authorizations == [(DataClassification.INTERNAL, ExecutionZone.LOCAL)]
    assert len(provider.calls) == 1
    assert provider.calls[0][1].max_output_tokens == 1024


@pytest.mark.parametrize("failure", ["deadline", "provider_error", "egress_denial"])
def test_optional_provider_failures_preserve_deterministic_mcp_response(failure):
    gate = _Gate() if failure == "deadline" else None
    provider = _Provider(
        gate,
        error=RuntimeError("synthetic unavailable")
        if failure == "provider_error"
        else None,
    )
    zone = (
        ExecutionZone.PUBLIC_CLOUD
        if failure == "egress_denial"
        else ExecutionZone.LOCAL
    )
    classification = (
        DataClassification.RESTRICTED
        if failure == "egress_denial"
        else DataClassification.INTERNAL
    )
    server, _, authorizations = _reasoning_server(
        provider, timeout=0.05, zone=zone, classification=classification
    )

    async def run():
        baseline = await server.call_tool("analyze_run", {"run_id": str(RUN_ID)})
        task = asyncio.create_task(
            server.call_tool(
                "analyze_run", {"run_id": str(RUN_ID), "reasoning": "explain"}
            )
        )
        try:
            if gate is not None:
                assert await asyncio.to_thread(gate.started.wait, 3)
                independent = await asyncio.wait_for(
                    server.call_tool("analyze_run", {"run_id": str(RUN_ID)}), 0.5
                )
                assert independent.structured_content == baseline.structured_content
                assert not gate.release.is_set()
            explained = (await asyncio.wait_for(task, 0.5)).structured_content
            if gate is not None:
                assert not gate.release.is_set()
            assert explained["reasoning"]["status"] == (
                "not_allowed" if failure == "egress_denial" else "unavailable"
            )
            assert {k: v for k, v in explained.items() if k != "reasoning"} == {
                k: v for k, v in baseline.structured_content.items() if k != "reasoning"
            }
        finally:
            if gate is not None:
                gate.release.set()
                assert await asyncio.to_thread(gate.finished.wait, 3)
            await asyncio.gather(task, return_exceptions=True)

    asyncio.run(run())
    assert authorizations == [(classification, zone)]
    if failure == "egress_denial":
        assert not provider.calls


@pytest.mark.parametrize("operation", ["document", "explanation"])
def test_cancelled_request_discards_late_worker_error_without_unhandled_exception(
    operation,
):
    gate = _Gate()
    errors = []
    published = []

    async def run():
        loop = asyncio.get_running_loop()
        loop.set_exception_handler(lambda _loop, event: errors.append(event))
        if operation == "explanation":
            server, _, _ = _reasoning_server(
                _Provider(gate, RuntimeError("synthetic late failure"))
            )

            async def invoke():
                return await server.call_tool(
                    "analyze_run", {"run_id": str(RUN_ID), "reasoning": "explain"}
                )

        else:

            class Reader:
                def get_document(self, document_id, security_context):
                    try:
                        gate.block()
                        raise RuntimeError("synthetic late failure")
                    finally:
                        gate.finished.set()

            app = create_app(FakeRunService(), document_content_reader=Reader())

            async def invoke():
                async with httpx.AsyncClient(
                    transport=httpx.ASGITransport(app=app), base_url="http://fixture"
                ) as client:
                    return await client.get(
                        "/api/v1/documents/doc-quality-procedure/download",
                        params={"user_clearance": "CONFIDENTIAL"},
                    )

        async def request():
            published.append(await invoke())

        task = asyncio.create_task(request())
        try:
            assert await asyncio.to_thread(gate.started.wait, 3)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(task, 0.5)
            assert not gate.release.is_set()
            assert not published
        finally:
            gate.release.set()
            await asyncio.gather(task, return_exceptions=True)
            await loop.shutdown_default_executor()
        assert gate.finished.is_set()
        assert not [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]

    asyncio.run(run())
    assert not errors
    assert not published

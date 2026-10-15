"""Bounded actual SDK/HTTP lifecycle using event-controlled synthetic transports."""

import asyncio
import gzip
import json
from contextvars import ContextVar
from functools import partial
from threading import Event
from types import SimpleNamespace

import httpx
import pytest
from opentelemetry import context as otel_context
from test_openai_compatible_llm_client import (
    FakeOpenAIClient,
    chat_with_policy,
    create_configuration,
)
from test_rca_reasoning import RUN_ID, _profile, _report, _resolver, _valid_output
from test_telemetry import _recording_telemetry

from industrial_ai_agent.agent.llm import LLMMessage, LLMRequest, MessageRole, ModelId
from industrial_ai_agent.agent.model_egress import ExecutionZone
from industrial_ai_agent.application.rca_reasoning import LlmRcaReasoner
from industrial_ai_agent.domain.security import DataClassification
from industrial_ai_agent.infrastructure import rca_mcp_server
from industrial_ai_agent.infrastructure.llm.deadline_transport import (
    DeadlineHTTPTransport,
)
from industrial_ai_agent.infrastructure.llm.openai_compatible import (
    OpenAICompatibleLLMClient,
)
from industrial_ai_agent.infrastructure.rca_mcp_server import (
    _reasoning_llm_client,
    _ReasoningWorkers,
    create_rca_mcp_server,
)

_CONTEXT = ContextVar("c02_request_context", default=None)


class _Tracker:
    def __init__(self, mode="blocked"):
        self.mode = mode
        self.started = asyncio.Queue()
        self.release = asyncio.Event()
        self.active = 0
        self.peak = 0
        self.calls = 0
        self.closed = 0
        self.cancelled = 0
        self.contexts = []
        self.requests = []

    def transport(self):
        tracker = self

        class Transport(httpx.AsyncBaseTransport):
            async def handle_async_request(self, request):
                tracker.calls += 1
                tracker.active += 1
                tracker.peak = max(tracker.peak, tracker.active)
                tracker.contexts.append(
                    (_CONTEXT.get(), otel_context.get_value("c02-trace"))
                )
                tracker.requests.append(request)
                tracker.started.put_nowait(None)
                try:
                    if tracker.mode == "blocked":
                        await tracker.release.wait()
                    if tracker.mode == "network_timeout":
                        raise httpx.ReadTimeout("Synthetic timeout", request=request)
                    if tracker.mode == "error":
                        return httpx.Response(
                            503, json={"error": "synthetic unavailable"}
                        )
                    payload = {
                        "id": "synthetic",
                        "object": "chat.completion",
                        "created": 0,
                        "model": "synthetic",
                        "choices": [
                            {
                                "index": 0,
                                "message": {
                                    "role": "assistant",
                                    "content": json.dumps(_valid_output()),
                                },
                                "finish_reason": "stop",
                            }
                        ],
                    }
                    if tracker.mode == "compressed":
                        encoded = gzip.compress(json.dumps(payload).encode())
                        return httpx.Response(
                            200,
                            stream=httpx.ByteStream(encoded),
                            headers={
                                "content-encoding": "gzip",
                                "content-type": "application/json",
                                "content-length": str(len(encoded)),
                            },
                        )
                    return httpx.Response(
                        200,
                        json=payload,
                    )
                except asyncio.CancelledError:
                    tracker.cancelled += 1
                    raise
                finally:
                    tracker.active -= 1

            async def aclose(self):
                tracker.closed += 1

        return Transport()


def _setup(
    tracker,
    *,
    budget=0.1,
    classification=DataClassification.INTERNAL,
    zone=ExecutionZone.LOCAL,
    telemetry=None,
):
    configuration = create_configuration(
        supports_structured_output=True, supports_reasoning_effort=True
    )
    if zone is not ExecutionZone.LOCAL:
        configuration = configuration.model_copy(
            update={
                "models": tuple(
                    model.model_copy(update={"execution_zone": zone})
                    for model in configuration.models
                )
            }
        )
    adapter = OpenAICompatibleLLMClient(
        configuration,
        http_client_factory=lambda: httpx.Client(
            transport=DeadlineHTTPTransport(transport_factory=tracker.transport),
            trust_env=False,
            follow_redirects=False,
        ),
    )
    reasoner = LlmRcaReasoner(
        model_resolver=_resolver(
            _profile("local_quality", ExecutionZone.LOCAL), classification
        ),
        client_factory=lambda label, focus: _reasoning_llm_client(
            adapter,
            configuration=configuration,
            classification=label,
            focus=focus,
            telemetry=telemetry,
        ),
        timeout_seconds=budget,
    )

    class Analysis:
        async def analyze(self, run_id, security_context):
            assert security_context.authenticated
            return _report(classification=classification)

    server = create_rca_mcp_server(
        analysis_service=Analysis(), reasoner=reasoner, telemetry=telemetry
    )
    return server, adapter


async def _call(server, *, explain=True):
    result = await server.call_tool(
        "analyze_run",
        {"run_id": str(RUN_ID), "reasoning": "explain" if explain else "none"},
    )
    return result.structured_content


def _deterministic(result):
    return {key: value for key, value in result.items() if key != "reasoning"}


def test_sdk_operation_terminates_at_total_deadline_and_recovers_capacity():
    tracker = _Tracker()
    server, adapter = _setup(tracker)
    # Warm lazy SDK imports/construction without transport access; measure the operation.
    _ = adapter._get_client(ModelId("local_quality")).chat.completions

    async def run():
        async with server.settings.lifespan(server):
            baseline = await _call(server, explain=False)
            for _ in range(3):
                response = await asyncio.wait_for(_call(server), 1)
                assert response["reasoning"]["status"] == "unavailable"
                assert _deterministic(response) == _deterministic(baseline)
            # Lifespan exit drains even the last job whose caller deadline won the race.
        assert tracker.active == 0
        assert tracker.cancelled == 3
        assert tracker.closed == 3
        assert tracker.peak <= 4

        recovered, recovered_adapter = _setup(tracker)
        tracker.mode = "success"
        async with recovered.settings.lifespan(recovered):
            assert (await _call(recovered))["reasoning"]["status"] == "available"
        recovered_adapter.close()

    try:
        asyncio.run(run())
    finally:
        adapter.close()


def test_owned_capacity_stays_held_after_timeouts_until_actual_worker_exit():
    """Even a deliberately non-cooperative fake cannot accumulate extra workers."""
    release = Event()
    started = [Event(), Event()]
    completed = []
    workers = _ReasoningWorkers(2)

    def block(index):
        started[index].set()
        assert release.wait(3)
        completed.append(index)
        raise RuntimeError("Synthetic late worker error")

    async def run():
        errors = []
        asyncio.get_running_loop().set_exception_handler(
            lambda _loop, event: errors.append(event)
        )
        calls = [
            asyncio.create_task(workers.run(partial(block, i), 0.05)) for i in range(2)
        ]
        try:
            for event in started:
                assert await asyncio.to_thread(event.wait, 1)
            results = await asyncio.gather(*calls, return_exceptions=True)
            assert all(isinstance(value, TimeoutError) for value in results)
            assert workers.pending_count == 2
            for _ in range(5):
                with pytest.raises(TimeoutError, match="capacity"):
                    await workers.run(lambda: None, 0.05)
            assert not completed
        finally:
            release.set()
            await asyncio.gather(*tuple(workers._pending), return_exceptions=True)
        assert workers.pending_count == 0
        assert await workers.run(lambda: "recovered", 0.5) == "recovered"
        await workers.close()
        assert not errors

    asyncio.run(run())
    assert sorted(completed) == [0, 1]


def test_concurrent_sdk_timeouts_admit_at_most_four_and_recover_same_server(
    monkeypatch,
):
    owners = []

    class RecordingWorkers(_ReasoningWorkers):
        def __init__(self, capacity):
            super().__init__(capacity)
            owners.append(self)

    monkeypatch.setattr(rca_mcp_server, "_ReasoningWorkers", RecordingWorkers)
    tracker = _Tracker()
    server, adapter = _setup(tracker, budget=0.3)

    async def run():
        async with server.settings.lifespan(server):
            calls = [asyncio.create_task(_call(server)) for _ in range(4)]
            for _ in range(4):
                await asyncio.wait_for(tracker.started.get(), 1)
            rejected = await asyncio.wait_for(_call(server), 0.1)
            assert rejected["reasoning"]["status"] == "unavailable"
            assert tracker.calls == 4
            independent = await asyncio.wait_for(_call(server, explain=False), 0.1)
            assert independent["run_id"] == str(RUN_ID)
            results = await asyncio.gather(*calls)
            assert all(item["reasoning"]["status"] == "unavailable" for item in results)
            # Observe actual completion before reusing the same server and SDK client.
            await asyncio.gather(*tuple(owners[0]._pending), return_exceptions=True)
            assert tracker.active == 0
            assert tracker.cancelled == tracker.closed == 4
            assert owners[0].pending_count == 0
            tracker.mode = "success"
            recovered = await _call(server)
            assert recovered["reasoning"]["status"] == "available"
        assert tracker.active == 0
        assert tracker.peak == 4
        assert tracker.closed == tracker.calls == 5

    try:
        asyncio.run(run())
    finally:
        adapter.close()


@pytest.mark.parametrize("outcome", ["deadline", "late_success", "late_error"])
def test_request_cancellation_is_prompt_provider_is_bounded_and_late_result_not_published(
    outcome,
):
    tracker = _Tracker()
    server, adapter = _setup(tracker, budget=0.2)
    responses = []
    errors = []

    async def run():
        asyncio.get_running_loop().set_exception_handler(
            lambda _loop, event: errors.append(event)
        )
        async with server.settings.lifespan(server):

            async def request():
                responses.append(await _call(server))

            task = asyncio.create_task(request())
            await asyncio.wait_for(tracker.started.get(), 1)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(task, 0.05)
            assert tracker.active == 1
            assert not responses
            assert (await _call(server, explain=False))["run_id"] == str(RUN_ID)
            if outcome != "deadline":
                if outcome == "late_error":
                    tracker.mode = "error"
                tracker.release.set()
        assert tracker.active == 0
        assert tracker.closed == 1
        assert tracker.cancelled == (1 if outcome == "deadline" else 0)
        assert not responses
        assert not errors

    try:
        asyncio.run(run())
    finally:
        adapter.close()


@pytest.mark.parametrize("mode", ["success", "compressed", "network_timeout", "error"])
def test_provider_outcomes_preserve_deterministic_report(mode):
    tracker = _Tracker(mode)
    server, adapter = _setup(tracker, budget=1)

    async def run():
        async with server.settings.lifespan(server):
            baseline = await _call(server, explain=False)
            result = await _call(server)
            assert _deterministic(result) == _deterministic(baseline)
            assert result["reasoning"]["status"] == (
                "available" if mode in {"success", "compressed"} else "unavailable"
            )
        assert tracker.closed == tracker.calls == 1

    try:
        asyncio.run(run())
    finally:
        adapter.close()


def test_egress_denies_before_transport_even_after_routing_selection():
    tracker = _Tracker("success")
    server, adapter = _setup(
        tracker,
        classification=DataClassification.RESTRICTED,
        zone=ExecutionZone.PUBLIC_CLOUD,
    )

    async def run():
        async with server.settings.lifespan(server):
            assert (await _call(server))["reasoning"]["status"] == "not_allowed"
        assert tracker.calls == tracker.closed == 0

    try:
        asyncio.run(run())
    finally:
        adapter.close()


def test_context_and_metadata_only_provider_timeout_telemetry(caplog):
    tracker = _Tracker()
    telemetry, exporter = _recording_telemetry()
    server, adapter = _setup(tracker, telemetry=telemetry)

    async def run():
        token = _CONTEXT.set("trusted-request")
        trace_token = otel_context.attach(
            otel_context.set_value("c02-trace", "synthetic-trace")
        )
        try:
            async with server.settings.lifespan(server):
                await _call(server)
        finally:
            otel_context.detach(trace_token)
            _CONTEXT.reset(token)

    try:
        asyncio.run(run())
        assert tracker.contexts == [("trusted-request", "synthetic-trace")]
        spans = [
            span for span in exporter.get_finished_spans() if span.name == "llm.call"
        ]
        assert len(spans) == 1
        assert spans[0].attributes["data.classification"] == "INTERNAL"
        assert spans[0].attributes["execution.zone"] == "LOCAL"
        assert spans[0].attributes["operation.status"] == "failure"
        assert "synthetic-trace" not in caplog.text
        assert _valid_output()["summary"] not in caplog.text
        payload = json.loads(tracker.requests[0].content)
        assert payload["max_tokens"] == 1024
        assert "timeout" not in payload
    finally:
        adapter.close()
        telemetry.shutdown()


@pytest.mark.parametrize("value", [0, -1, float("inf"), float("nan")])
def test_invalid_operation_deadlines_are_rejected(value):
    with pytest.raises(ValueError):
        LLMRequest(
            messages=(LLMMessage(role=MessageRole.USER, content="Synthetic"),),
            timeout_seconds=value,
        )


def test_total_deadline_covers_response_body_after_headers():
    tracker = _Tracker("success")
    body_started = asyncio.Event()
    body_closed = []
    never_released = asyncio.Event()

    class Body(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield b"{"
            body_started.set()
            await never_released.wait()

        async def aclose(self):
            body_closed.append(True)

    class Transport(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request):
            return httpx.Response(200, stream=Body())

        async def aclose(self):
            tracker.closed += 1

    tracker.transport = Transport
    server, adapter = _setup(tracker, budget=0.2)
    _ = adapter._get_client(ModelId("local_quality")).chat.completions

    async def run():
        async with server.settings.lifespan(server):
            task = asyncio.create_task(_call(server))
            await asyncio.wait_for(body_started.wait(), 1)
            assert (await asyncio.wait_for(task, 1))["reasoning"][
                "status"
            ] == "unavailable"
        assert body_closed
        assert tracker.closed == 1
        assert not never_released.is_set()

    try:
        asyncio.run(run())
    finally:
        adapter.close()


def test_rca_transport_budget_preserves_the_shared_sdk_phase_limit():
    tracker = _Tracker("success")
    server, adapter = _setup(tracker, budget=90)

    async def run():
        async with server.settings.lifespan(server):
            assert (await _call(server))["reasoning"]["status"] == "available"
        phases = tracker.requests[0].extensions["timeout"]
        assert phases == {"connect": 45.0, "read": 45.0, "write": 45.0, "pool": 45.0}

    try:
        asyncio.run(run())
    finally:
        adapter.close()


def test_shared_adapter_defaults_and_other_consumer_requests_are_unchanged():
    sdk = FakeOpenAIClient(
        SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content="Synthetic", tool_calls=None),
                    finish_reason="stop",
                )
            ]
        )
    )
    options = {}

    def factory(**kwargs):
        options.update(kwargs)
        return sdk

    adapter = OpenAICompatibleLLMClient(create_configuration(), client_factory=factory)
    messages = (LLMMessage(role=MessageRole.USER, content="Synthetic"),)
    try:
        chat_with_policy(
            adapter,
            ModelId("local_quality"),
            LLMRequest(messages=messages, timeout_seconds=0.1),
        )
        assert sdk.completions.parameters["timeout"] == 0.1
        assert options["timeout"] == 45.0
        assert options["max_retries"] == 0
        chat_with_policy(
            adapter, ModelId("local_quality"), LLMRequest(messages=messages)
        )
        assert "timeout" not in sdk.completions.parameters
        assert options["timeout"] == 45.0
    finally:
        adapter.close()

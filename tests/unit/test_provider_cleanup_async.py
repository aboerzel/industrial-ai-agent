"""PCLEAN service/provider lifecycle proofs; real SDK, synthetic HTTP only."""

import asyncio
import json
import os
import threading
import time
from contextlib import asynccontextmanager, contextmanager
from itertools import pairwise
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID, uuid4

import anyio
import httpx
import pytest
from openai import OpenAI
from test_fastapi_api import _create_app
from test_openai_compatible_llm_client import create_configuration
from test_r05_provider_client_ownership import MODEL, Probe, request

from industrial_ai_agent.agent.llm import LLMProviderError, ModelId
from industrial_ai_agent.agent.mcp_tool_provider import McpToolSession
from industrial_ai_agent.agent.model_egress import ModelExecutionAuthorizer
from industrial_ai_agent.agent.response_language import ResponseLanguage
from industrial_ai_agent.agent.run_classification_policy import (
    AgentRunClassificationPolicy,
    AgentRunProfile,
)
from industrial_ai_agent.agent.troubleshooting_run_service import (
    TroubleshootingRunService,
)
from industrial_ai_agent.infrastructure import (
    troubleshooting_run_composition as composition,
)
from industrial_ai_agent.infrastructure.api.run_store import InMemoryAgentRunStore
from industrial_ai_agent.infrastructure.llm.openai_compatible import (
    OpenAICompatibleLLMClient,
)

POLICY = AgentRunClassificationPolicy().resolve(AgentRunProfile.PUBLIC_INFORMATION)
# A 22 ms pulse normally measures 22–32 ms on Windows. 150 ms allows loaded CI
# scheduling while rejecting either original 350/750 ms event-loop freeze.
RESPONSIVE_SECONDS = 0.15


async def until(predicate):
    async with asyncio.timeout(15):
        while not predicate():
            await asyncio.sleep(0.005)


async def provider_started(probe, run):
    def ready():
        if run.done():
            run.result()
            raise AssertionError(
                "Run finished without reaching the synthetic transport"
            )
        return probe.started.is_set()

    await until(ready)


class Resolver:
    def resolve_model(self, *args, **kwargs):
        return SimpleNamespace(model=SimpleNamespace(model_id=ModelId("local_quality")))


class EmptyTools:
    @asynccontextmanager
    async def open_session(self):
        yield McpToolSession(
            tools=(),
            discovered_tool_names=(),
            server_name="synthetic",
            server_version="1",
            protocol_version="synthetic",
        )


class TransportProbe:
    """Observe actual adapter/SDK/HTTP ownership and completion ordering."""

    def __init__(self, *, fail=False):
        self.started, self.release, self.closing = (
            threading.Event(),
            threading.Event(),
            threading.Event(),
        )
        self.events = []
        self.requests = self.completions = self.sdk_closes = self.http_closes = 0
        self.adapter_closes = self.decrements = 0
        self.fail = fail
        self.adapter = None

    def record(self, name):
        self.events.append((name, time.monotonic(), threading.get_ident()))

    def transport(self, req):
        self.requests += 1
        self.record("request-start")
        self.started.set()
        try:
            assert self.release.wait(5), "Synthetic request was not released"
            if self.fail:
                raise httpx.ReadTimeout("synthetic private detail", request=req)
            return httpx.Response(
                200,
                json={
                    "id": "synthetic",
                    "object": "chat.completion",
                    "created": 0,
                    "model": "synthetic",
                    "choices": [
                        {
                            "index": 0,
                            "message": {"role": "assistant", "content": "Hello."},
                            "finish_reason": "stop",
                        }
                    ],
                },
            )
        finally:
            self.completions += 1
            self.record("request-complete")

    def factory(self, configuration):
        probe = self

        class OwnedHTTP(httpx.Client):
            def close(self):
                probe.http_closes += 1
                probe.record("http-close")
                super().close()

        class OwnedSDK(OpenAI):
            def close(self):
                assert probe.adapter._active_requests == 0
                probe.sdk_closes += 1
                probe.record("sdk-close")
                super().close()

        class Adapter(OpenAICompatibleLLMClient):
            def close(self):
                probe.adapter_closes += 1
                probe.record("close-start")
                probe.closing.set()
                try:
                    super().close()
                finally:
                    probe.record("close-complete")

        self.adapter = Adapter(
            configuration,
            client_factory=OwnedSDK,
            http_client_factory=lambda: OwnedHTTP(
                transport=httpx.MockTransport(self.transport),
                trust_env=False,
                follow_redirects=False,
            ),
        )
        notify_all = self.adapter._lifecycle.notify_all

        def notified():
            # Observe the real decrement while its Condition lock is still held;
            # recording outside the context would race the draining close worker.
            if not self.adapter._closed:
                probe.decrements += 1
                probe.record("active-decrement")
            notify_all()

        self.adapter._lifecycle.notify_all = notified
        return self.adapter

    def assert_closed(self):
        assert self.requests == self.completions == self.decrements
        assert self.adapter_closes == self.sdk_closes == self.http_closes == 1
        assert self.adapter._closed and self.adapter._active_requests == 0
        assert not self.adapter._clients and not self.adapter._http_clients
        names = [entry[0] for entry in self.events]
        assert names.index("sdk-close") > max(
            i for i, name in enumerate(names) if name == "active-decrement"
        )
        assert names.index("sdk-close") < names.index("http-close")
        assert names.index("http-close") < names.index("close-complete")


def real_service(monkeypatch, probe):
    monkeypatch.setattr(composition, "OpenAICompatibleLLMClient", probe.factory)
    factory = composition._LangGraphTroubleshootingAgentFactory(
        configuration=create_configuration(
            supports_structured_output=True, supports_reasoning_effort=True
        ),
        mcp_tool_provider_factory=lambda policy: EmptyTools(),
        authorizer=ModelExecutionAuthorizer(),
    )
    return TroubleshootingRunService(model_resolver=Resolver(), agent_factory=factory)


async def independent_request(app=None):
    app = app or _create_app(object(), run_store=InMemoryAgentRunStore())
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://synthetic"
    ) as client:
        assert (await client.get("/health")).json() == {"status": "ok"}


def save_measurement(name, data):
    if directory := os.getenv("PCLEAN_EVIDENCE_DIR"):
        (Path(directory) / f"{name}.json").write_text(
            json.dumps(data, indent=2), encoding="utf-8"
        )


@pytest.mark.parametrize("delay", [0.35, 0.75], ids=["PCLEAN-03", "PCLEAN-04"])
def test_cancelled_production_graph_drains_off_loop(monkeypatch, delay):
    async def verify():
        loop_thread = threading.get_ident()
        probe = TransportProbe()
        service = real_service(monkeypatch, probe)
        app = _create_app(service, run_store=InMemoryAgentRunStore())
        ticks = []

        async def heartbeat():
            while True:
                ticks.append(time.monotonic())
                await asyncio.sleep(0.022)

        pulse = asyncio.create_task(heartbeat())
        run = asyncio.create_task(
            service.run_with_policy(
                "Hello.", run_policy=POLICY, response_language=ResponseLanguage.EN
            )
        )
        timer = None
        try:
            await provider_started(probe, run)
            ticks[:] = [time.monotonic()]
            timer = threading.Timer(delay, probe.release.set)
            timer.start()
            cancelled_at = time.monotonic()
            run.cancel()
            await until(probe.closing.is_set)
            assert probe.adapter._active_requests == 1
            # Measure from dispatch, so a stalled loop cannot hide behind a fast
            # measurement that only starts after provider drain finishes.
            independent_started_at = time.monotonic()
            await independent_request(app)
            independent_elapsed = time.monotonic() - independent_started_at
            assert independent_elapsed < RESPONSIVE_SECONDS
            assert not run.done() and not probe.release.is_set()
            assert probe.adapter._active_requests == 1
            with pytest.raises(asyncio.CancelledError):
                await run
            cleanup_completed_at = time.monotonic()
            await asyncio.sleep(0.04)
            gap = max(b - a for a, b in pairwise(ticks))
            save_measurement(
                f"post-{int(delay * 1000)}",
                {
                    "cancelled_at": cancelled_at,
                    "cleanup_completed_at": cleanup_completed_at,
                    "maximum_heartbeat_gap_seconds": gap,
                    "independent_request_seconds": independent_elapsed,
                    "active_calls_after": probe.adapter._active_requests,
                    "loop_thread": loop_thread,
                    "events": probe.events,
                },
            )
            assert gap < RESPONSIVE_SECONDS
            assert cleanup_completed_at - cancelled_at >= delay * 0.9
            assert all(
                thread != loop_thread
                for name, _, thread in probe.events
                if name.startswith("close-") or name in {"sdk-close", "http-close"}
            )
            assert (
                probe.requests == 1
            )  # Cancellation never retries or starts another decision.
            probe.assert_closed()
        finally:
            probe.release.set()
            if timer:
                timer.join()
            pulse.cancel()
            await asyncio.gather(run, pulse, return_exceptions=True)

    asyncio.run(verify())


@pytest.mark.parametrize(
    "mode", ["normal", "timeout", "exception", "duplicate", "scope"]
)
def test_production_provider_completion_paths(monkeypatch, mode):
    async def verify():
        probe = TransportProbe(fail=mode == "exception")
        service = real_service(monkeypatch, probe)

        async def invoke():
            if mode == "timeout":
                async with asyncio.timeout(0.10):
                    return await service.run_with_policy("Hello.", run_policy=POLICY)
            if mode == "scope":
                with anyio.CancelScope() as scope:
                    scopes.append(scope)
                    await service.run_with_policy("Hello.", run_policy=POLICY)
                assert scope.cancelled_caught
                return None
            return await service.run_with_policy("Hello.", run_policy=POLICY)

        scopes = []
        run = asyncio.create_task(invoke())
        try:
            await provider_started(probe, run)
            if mode == "duplicate":
                run.cancel()
            elif mode == "scope":
                scopes[0].cancel()
            if mode in {"duplicate", "scope", "timeout"}:
                await until(probe.closing.is_set)
                if mode == "duplicate":
                    for _ in range(3):
                        run.cancel()
                        await asyncio.sleep(0.01)
                assert not run.done() and not probe.adapter._closed
                await independent_request()
            probe.release.set()
            if mode == "timeout":
                with pytest.raises(TimeoutError):
                    await run
            elif mode == "exception":
                with pytest.raises(LLMProviderError):
                    await run
            elif mode == "duplicate":
                with pytest.raises(asyncio.CancelledError):
                    await run
            else:
                result = await run
                if mode == "normal":
                    assert result.final_answer == "The authorized check is complete."
                    # The real graph can normalize its final answer, reusing the
                    # same single SDK/HTTP client throughout all model decisions.
                    assert probe.requests >= 1
            probe.assert_closed()
            assert not any(
                t.get_name() == "provider-owned-lifecycle" for t in asyncio.all_tasks()
            )
        finally:
            probe.release.set()
            await asyncio.gather(run, return_exceptions=True)

    asyncio.run(verify())


def test_api_timeout_drains_provider_and_keeps_terminal_failure(monkeypatch):
    async def verify():
        probe = TransportProbe()
        service = real_service(monkeypatch, probe)
        store = InMemoryAgentRunStore()
        # Only the test app's execution budget is shortened; product defaults stay
        # unchanged. The transport remains blocked until API cleanup starts.
        app = _create_app(service, run_store=store, execution_timeout_seconds=1.0)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://synthetic"
        ) as client:
            run = asyncio.create_task(
                client.post(
                    "/api/v1/runs",
                    json={
                        "message": "Hello.",
                        "user_clearance": "RESTRICTED",
                    },
                )
            )
            try:
                await provider_started(probe, run)
                await until(probe.closing.is_set)
                begin = time.monotonic()
                assert (await client.get("/health")).json() == {"status": "ok"}
                assert time.monotonic() - begin < RESPONSIVE_SECONDS
                assert not run.done() and not probe.adapter._closed
                probe.release.set()
                response = await run
                assert response.status_code == 200
                payload = response.json()
                assert payload["status"] == "failed"
                assert payload["error"] == {
                    "code": "agent_execution_timeout",
                    "message": "The agent run exceeded its execution time limit.",
                    "failure_origin": "ORCHESTRATION",
                }
                stored = await store.get(UUID(payload["run_id"]))
                assert (
                    stored.error_code == "agent_execution_timeout"
                    and stored.result is None
                )
                await asyncio.sleep(0.04)
                assert (await store.get(stored.run_id)) == stored
                probe.assert_closed()
            finally:
                probe.release.set()
                await asyncio.gather(run, return_exceptions=True)

    asyncio.run(verify())


class ProbeFactory:
    def __init__(self, probe, *, calls=1):
        self.probe, self.calls = probe, calls

    @contextmanager
    def open_agent(self, **kwargs):
        probe, calls = self.probe, self.calls

        class Agent:
            async def aanswer_via_mcp(self, *args, **kwargs):
                await asyncio.gather(
                    *[
                        asyncio.to_thread(probe.checked.chat, MODEL, request())
                        for _ in range(calls)
                    ]
                )

            astart_via_mcp = aanswer_via_mcp
            aresume_via_mcp = aanswer_via_mcp

        with probe.adapter:
            yield Agent()


class Checkpointer:
    def __init__(self, probe):
        self.probe = probe

    @asynccontextmanager
    async def open(self):
        try:
            yield object()
        finally:
            assert self.probe.adapter._closed
            assert self.probe.adapter._active_requests == 0


def probe_service(probe, *, calls=1):
    return TroubleshootingRunService(
        model_resolver=Resolver(),
        agent_factory=ProbeFactory(probe, calls=calls),
        checkpointer_factory=Checkpointer(probe),
    )


@pytest.mark.parametrize("method", ["run", "start", "resume"])
def test_all_service_entrypoints_drain_multiple_active_calls(method):
    async def verify():
        probe = Probe(cascade=False)
        probe.provider_release.clear()
        service = probe_service(probe, calls=2)
        if method == "run":
            operation = service.run_with_policy("Hello.", run_policy=POLICY)
        elif method == "start":
            operation = service.start("Hello.", run_id=uuid4(), run_policy=POLICY)
        else:
            operation = service.resume(
                run_id=uuid4(),
                model_id=MODEL.value,
                data_classification=POLICY.data_classification,
                run_profile=POLICY.run_profile,
                decision="reject",
            )
        run = asyncio.create_task(operation)
        try:
            await until(lambda: probe.adapter._active_requests == 2)
            run.cancel()
            await until(lambda: probe.adapter._closing)
            assert not probe.clients[0].close_calls
            assert not probe.http_clients[0].is_closed
            with pytest.raises(RuntimeError, match="closed"):
                probe.checked.chat(MODEL, request())
            await independent_request()
            assert not run.done()
            probe.provider_release.set()
            with pytest.raises(asyncio.CancelledError):
                await run
            assert probe.adapter._active_requests == probe.active == 0
            assert probe.factory_calls == 1
            assert (
                probe.clients[0].close_calls == probe.http_clients[0].close_calls == 1
            )
            probe.adapter.close()  # Final/idempotent, never republishes a client.
            with pytest.raises(RuntimeError, match="closed"):
                probe.checked.chat(MODEL, request())
            assert probe.factory_calls == 1 and probe.clients[0].close_calls == 1
        finally:
            probe.provider_release.set()
            await asyncio.gather(run, return_exceptions=True)

    asyncio.run(verify())


def test_cancelled_cleanup_respects_shared_worker_capacity():
    async def verify():
        limiter = anyio.to_thread.current_default_thread_limiter()
        original_capacity = limiter.total_tokens
        limiter.total_tokens = 2
        probes = [Probe(cascade=False) for _ in range(8)]
        for probe in probes:
            probe.provider_release.clear()
        runs = [
            asyncio.create_task(
                probe_service(probe).run_with_policy("Hello.", run_policy=POLICY)
            )
            for probe in probes
        ]
        try:
            await until(lambda: all(p.adapter._active_requests == 1 for p in probes))
            for run in runs:
                run.cancel()
            await until(lambda: sum(p.adapter._closing for p in probes) == 2)
            await asyncio.sleep(0.03)
            assert limiter.borrowed_tokens == 2
            assert sum(p.adapter._closing for p in probes) == 2
            begin = time.monotonic()
            await independent_request()
            assert time.monotonic() - begin < RESPONSIVE_SECONDS
            assert all(not run.done() for run in runs)
            # Repeated cancellation while queued must not abandon mandatory exits.
            for run in runs:
                run.cancel()
            for probe in probes:
                probe.provider_release.set()
            results = await asyncio.gather(*runs, return_exceptions=True)
            assert all(isinstance(result, asyncio.CancelledError) for result in results)
            assert limiter.borrowed_tokens == 0
            for probe in probes:
                assert probe.adapter._closed and probe.adapter._active_requests == 0
                assert (
                    probe.clients[0].close_calls
                    == probe.http_clients[0].close_calls
                    == 1
                )
            assert not any(
                t.get_name() == "provider-owned-lifecycle" for t in asyncio.all_tasks()
            )
        finally:
            for probe in probes:
                probe.provider_release.set()
            await asyncio.gather(*runs, return_exceptions=True)
            limiter.total_tokens = original_capacity

    asyncio.run(verify())


@pytest.mark.parametrize("cancel", [False, True])
def test_acquisition_failure_or_cancellation_preserves_context_ownership(cancel):
    async def verify():
        entered, release = threading.Event(), threading.Event()
        trace = []
        loop_thread = threading.get_ident()

        class Factory:
            @contextmanager
            def open_agent(self, **kwargs):
                try:
                    entered.set()
                    assert release.wait(5)
                    if not cancel:
                        raise RuntimeError("synthetic construction failure")
                    yield object()
                finally:
                    trace.append(threading.get_ident())

        service = TroubleshootingRunService(
            model_resolver=Resolver(), agent_factory=Factory()
        )
        run = asyncio.create_task(service.run_with_policy("Hello.", run_policy=POLICY))
        try:
            await until(entered.is_set)
            if cancel:
                run.cancel()
                await asyncio.sleep(0.02)
                run.cancel()
            await independent_request()
            assert not run.done()
            release.set()
            with pytest.raises(asyncio.CancelledError if cancel else RuntimeError):
                await run
            assert len(trace) == 1 and trace[0] != loop_thread
        finally:
            release.set()
            await asyncio.gather(run, return_exceptions=True)

    asyncio.run(verify())

"""Deterministic provider cache/transport ownership; no provider or network access."""

import asyncio
import json
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
from threading import Barrier, Event, Lock
from types import SimpleNamespace

import httpx
import pytest
from openai import OpenAI
from test_openai_compatible_llm_client import create_configuration
from test_rca_reasoning import RUN_ID, _profile, _report, _resolver, _valid_output

from industrial_ai_agent.agent.llm import LLMMessage, LLMRequest, MessageRole, ModelId
from industrial_ai_agent.agent.model_egress import (
    EgressCheckedLLMClient,
    ExecutionZone,
    ModelEgressDeniedError,
)
from industrial_ai_agent.domain.security import DataClassification
from industrial_ai_agent.infrastructure import rca_mcp_server as rca
from industrial_ai_agent.infrastructure.llm.configuration import AuthenticationMode
from industrial_ai_agent.infrastructure.llm.openai_compatible import (
    OpenAICompatibleLLMClient,
)

MODEL = ModelId("local_quality")


def request():
    return LLMRequest(
        messages=(LLMMessage(role=MessageRole.USER, content="SYNTHETIC R05"),)
    )


def completion(content):
    return SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(content=content, tool_calls=None),
                finish_reason="stop",
            )
        ],
        usage=None,
    )


class OwnedHTTP(httpx.Client):
    def __init__(self):
        super().__init__(
            transport=httpx.MockTransport(
                lambda _: pytest.fail("Fake SDK must not send network requests")
            ),
            trust_env=False,
            follow_redirects=False,
        )
        self.close_calls = 0

    def close(self):
        self.close_calls += 1
        super().close()


class SDK:
    def __init__(self, probe, http, identity):
        self.probe, self.http, self.identity = probe, http, identity
        self.close_calls = self.calls = 0
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

    def create(self, **kwargs):
        assert not self.close_calls and not self.http.is_closed
        with self.probe.lock:
            self.calls += 1
            self.probe.active += 1
            self.probe.peak = max(self.probe.peak, self.probe.active)
            self.probe.started_calls += 1
        self.probe.provider_started.set()
        try:
            if self.probe.operation_barrier is not None:
                self.probe.operation_barrier.wait(timeout=4)
            assert self.probe.provider_release.wait(5), (
                "Provider fixture release missing"
            )
            assert not self.close_calls and not self.http.is_closed
            return completion(self.probe.content or self.identity)
        finally:
            with self.probe.lock:
                self.probe.active -= 1

    def close(self):
        assert self.probe.active == 0, "Close must follow active request completion"
        self.close_calls += 1
        if self.probe.cascade:
            self.http.close()
        if self.probe.fail_close:
            raise RuntimeError("Synthetic SDK close failure")


class Probe:
    def __init__(self, configuration=None, *, blocked=False, cascade=True):
        self.configuration = configuration or create_configuration(
            supports_structured_output=True, supports_reasoning_effort=True
        )
        self.lock = Lock()
        self.factory_started, self.factory_release = Event(), Event()
        if not blocked:
            self.factory_release.set()
        self.provider_started, self.provider_release = Event(), Event()
        self.provider_release.set()
        self.factory_calls = self.credentials = self.active = self.peak = (
            self.started_calls
        ) = 0
        self.clients, self.http_clients, self.factory_arguments = [], [], []
        self.failures = 0
        self.cascade, self.fail_close = cascade, False
        self.operation_barrier = self.content = None
        self.adapter = OpenAICompatibleLLMClient(
            self.configuration,
            environment={"SYNTHETIC_A": "synthetic-a", "SYNTHETIC_B": "synthetic-b"},
            client_factory=self.factory,
            http_client_factory=self.http_factory,
        )
        original = self.adapter._resolve_api_key

        def credential(config):
            self.credentials += 1
            return original(config)

        self.adapter._resolve_api_key = credential
        self.checked = EgressCheckedLLMClient(
            self.adapter, self.configuration, DataClassification.PUBLIC
        )

    def http_factory(self):
        client = OwnedHTTP()
        self.http_clients.append(client)
        return client

    def factory(self, **kwargs):
        self.factory_calls += 1
        self.factory_arguments.append(kwargs)
        self.factory_started.set()
        assert self.factory_release.wait(5), "Construction fixture release missing"
        if self.failures:
            self.failures -= 1
            raise RuntimeError("Synthetic construction failure")
        client = SDK(
            self, kwargs["http_client"], f"synthetic-client-{len(self.clients) + 1}"
        )
        self.clients.append(client)
        return client

    def call(self, model=MODEL):
        return self.checked.chat(model, request()).text

    def assert_closed(self):
        assert all(client.close_calls == 1 for client in self.clients)
        assert all(
            client.is_closed and client.close_calls == 1 for client in self.http_clients
        )
        assert not self.adapter._clients and not self.adapter._http_clients
        assert self.adapter._closed and self.adapter._active_requests == 0


@pytest.fixture(autouse=True)
def owned_probe_cleanup(monkeypatch):
    instances = []
    original = Probe.__init__

    def track(self, *args, **kwargs):
        original(self, *args, **kwargs)
        instances.append(self)

    monkeypatch.setattr(Probe, "__init__", track)
    yield
    for probe in instances:
        probe.factory_release.set()
        probe.provider_release.set()
        probe.adapter.close()
        probe.assert_closed()


@pytest.mark.parametrize("callers", [2, 8])
def test_concurrent_cold_same_model_creates_one_owned_client(callers):
    probe = Probe(blocked=True)
    ready = Barrier(callers + 1)

    def call():
        ready.wait(timeout=5)
        return probe.call()

    with ThreadPoolExecutor(max_workers=callers) as pool:
        futures = [pool.submit(call) for _ in range(callers)]
        try:
            ready.wait(timeout=5)
            assert probe.factory_started.wait(4)
        finally:
            probe.factory_release.set()
        results = [future.result(timeout=8) for future in futures]
    assert results == [probe.clients[0].identity] * callers
    assert probe.factory_calls == len(probe.clients) == len(probe.adapter._clients) == 1
    assert probe.clients[0].calls == callers
    probe.adapter.close()
    probe.assert_closed()


def two_models():
    config = create_configuration()
    first = config.models[0].model_copy(
        update={
            "authentication": AuthenticationMode.API_KEY,
            "api_key_env": "SYNTHETIC_A",
        }
    )
    second = first.model_copy(
        update={
            "id": "second_model",
            "provider_model": "synthetic-other-model",
            "api_key_env": "SYNTHETIC_B",
        }
    )
    # Validate enum/config types, rather than using caller labels as authorization.
    return type(config).model_validate(
        {"models": [first.model_dump(mode="json"), second.model_dump(mode="json")]}
    )


def test_different_models_with_same_endpoint_retain_distinct_clients_and_credentials():
    probe = Probe(two_models())
    ready = Barrier(9)
    models = [MODEL, ModelId("second_model")] * 4

    def call(model):
        ready.wait(timeout=5)
        return probe.call(model)

    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = [pool.submit(call, model) for model in models]
        ready.wait(timeout=5)
        results = [future.result(timeout=8) for future in futures]
    assert len(set(results)) == probe.factory_calls == len(probe.clients) == 2
    assert set(probe.adapter._clients) == {model.value for model in models}
    assert len({args["base_url"] for args in probe.factory_arguments}) == 1
    assert {args["api_key"] for args in probe.factory_arguments} == {
        "synthetic-a",
        "synthetic-b",
    }
    probe.adapter.close()
    probe.adapter.close()
    probe.assert_closed()


def test_failed_construction_cleans_transport_and_next_call_can_retry():
    probe = Probe()
    probe.failures = 1
    with pytest.raises(RuntimeError, match="Synthetic construction failure"):
        probe.call()
    assert probe.factory_calls == 1 and not probe.adapter._clients
    assert probe.http_clients[0].is_closed and probe.http_clients[0].close_calls == 1
    assert probe.adapter._active_requests == 0
    assert probe.call() == probe.clients[0].identity
    probe.adapter.close()
    assert probe.factory_calls == 2 and len(probe.clients) == 1
    probe.assert_closed()


def test_http_factory_failure_before_resource_return_leaves_no_poisoned_cache():
    probe = Probe()

    def fail_before_creation():
        raise RuntimeError("Synthetic HTTP factory failure")

    probe.adapter._http_client_factory = fail_before_creation
    with pytest.raises(RuntimeError, match="Synthetic HTTP factory failure"):
        probe.call()
    assert not probe.adapter._clients and not probe.adapter._http_clients
    assert probe.factory_calls == len(probe.http_clients) == 0
    probe.adapter._http_client_factory = probe.http_factory
    probe.call()
    probe.adapter.close()
    probe.assert_closed()


def test_unused_optional_model_remains_lazy_with_missing_credentials():
    probe = Probe(two_models())
    del probe.adapter._environment["SYNTHETIC_B"]
    assert probe.credentials == probe.factory_calls == len(probe.http_clients) == 0
    probe.call()
    with pytest.raises(ValueError, match="Missing API key environment variable"):
        probe.call(ModelId("second_model"))
    assert probe.factory_calls == len(probe.clients) == len(probe.http_clients) == 1
    assert set(probe.adapter._clients) == {MODEL.value}
    probe.adapter.close()
    probe.assert_closed()


def test_failed_first_constructor_releases_lock_for_waiting_caller():
    probe = Probe(blocked=True)
    probe.failures = 1
    ready = Barrier(3)

    def call():
        ready.wait(timeout=5)
        return probe.call()

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(call) for _ in range(2)]
        try:
            ready.wait(timeout=5)
            assert probe.factory_started.wait(4)
        finally:
            probe.factory_release.set()
        outcomes = []
        for future in futures:
            try:
                outcomes.append(future.result(timeout=8))
            except RuntimeError as error:
                assert str(error) == "Synthetic construction failure"
                outcomes.append("failed")
    assert sorted(outcomes) == ["failed", "synthetic-client-1"]
    assert probe.factory_calls == 2 and len(probe.clients) == 1
    probe.adapter.close()
    probe.assert_closed()


@pytest.mark.parametrize("cascade", [False, True])
def test_adapter_owns_httpx_even_when_injected_sdk_does_not_close_it(cascade):
    probe = Probe(cascade=cascade)
    probe.call()
    probe.adapter.close()
    probe.adapter.close()
    probe.assert_closed()


def test_real_openai_sdk_close_cascades_to_owned_httpx_without_duplicate_close():
    http = OwnedHTTP()
    adapter = OpenAICompatibleLLMClient(
        create_configuration(), client_factory=OpenAI, http_client_factory=lambda: http
    )
    client = adapter._get_client(MODEL)
    assert client._client is http and not http.is_closed
    adapter.close()
    adapter.close()
    assert client.is_closed() and http.is_closed and http.close_calls == 1
    with pytest.raises(RuntimeError, match="adapter is closed"):
        adapter._get_client(MODEL)


def test_warm_provider_operations_overlap_outside_lifecycle_lock():
    probe = Probe()
    probe.call()
    probe.operation_barrier = Barrier(2)
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(probe.call) for _ in range(2)]
        assert [future.result(timeout=8) for future in futures] == [
            probe.clients[0].identity
        ] * 2
    assert probe.peak == 2 and probe.factory_calls == 1
    probe.adapter.close()
    probe.assert_closed()


@pytest.mark.parametrize("warm", [False, True])
def test_close_racing_initialization_or_active_request_waits_without_use_after_close(
    warm,
):
    probe = Probe(blocked=not warm)
    if warm:
        probe.call()
    probe.provider_started.clear()
    probe.provider_release.clear()
    close_started, close_done = Event(), Event()

    def close():
        close_started.set()
        probe.adapter.close()
        close_done.set()

    with ThreadPoolExecutor(max_workers=3) as pool:
        call = pool.submit(probe.call)
        try:
            assert (probe.provider_started if warm else probe.factory_started).wait(4)
            shutdown = pool.submit(close)
            assert close_started.wait(4)
            assert not close_done.wait(0.05)
            probe.factory_release.set()
            assert probe.provider_started.wait(4)
            assert not close_done.is_set() and all(
                not c.close_calls for c in probe.clients
            )
            repeated_shutdown = pool.submit(probe.adapter.close)
        finally:
            probe.factory_release.set()
            probe.provider_release.set()
        assert call.result(timeout=8) == probe.clients[0].identity
        shutdown.result(timeout=8)
        repeated_shutdown.result(timeout=8)
    with pytest.raises(RuntimeError, match="adapter is closed"):
        probe.call()
    assert probe.factory_calls == 1
    probe.assert_closed()


def test_cleanup_attempts_all_clients_and_httpx_even_if_sdk_close_raises():
    probe = Probe(two_models(), cascade=False)
    probe.call()
    probe.call(ModelId("second_model"))
    probe.fail_close = True
    with pytest.raises(RuntimeError, match="Synthetic SDK close failure"):
        probe.adapter.close()
    probe.adapter.close()
    probe.assert_closed()


def test_r01_unauthorized_call_cannot_resolve_credentials_or_mutate_client_cache():
    probe = Probe()
    with pytest.raises(ModelEgressDeniedError):
        probe.adapter.chat(MODEL, request())
    assert (
        probe.credentials
        == probe.factory_calls
        == len(probe.clients)
        == len(probe.http_clients)
        == 0
    )
    assert probe.adapter._clients == probe.adapter._http_clients == {}
    probe.adapter.close()


def test_c04_cloud_http_is_denied_before_credentials_or_client_factory():
    config = create_configuration()
    model = config.models[0].model_copy(
        update={
            "execution_zone": ExecutionZone.PUBLIC_CLOUD,
            "base_url": "http://provider.invalid/v1",
        }
    )
    probe = Probe(config.model_copy(update={"models": (model,)}))
    with pytest.raises(PermissionError, match="must use HTTPS"):
        probe.call()
    assert probe.credentials == probe.factory_calls == len(probe.http_clients) == 0
    probe.adapter.close()


async def until(predicate):
    async with asyncio.timeout(4):
        while not predicate():
            await asyncio.sleep(0.002)


def test_owned_rca_adapter_closes_only_after_c02_drains_cancelled_shared_workers(
    monkeypatch,
):
    probe = Probe(blocked=True)
    probe.content = json.dumps(_valid_output())
    probe.provider_release.clear()
    provider_errors = []
    original_chat = probe.adapter.chat

    def observed_chat(*args):
        try:
            return original_chat(*args)
        except Exception as error:
            provider_errors.append(type(error).__name__)
            raise

    monkeypatch.setattr(probe.adapter, "chat", observed_chat)
    monkeypatch.setattr(rca, "load_model_catalog", lambda _: probe.configuration)
    monkeypatch.setattr(
        rca, "OpenAICompatibleLLMClient", lambda *args, **kwargs: probe.adapter
    )
    monkeypatch.setattr(
        rca, "PostgreSqlModelAssignmentRepository", lambda *args: object()
    )
    monkeypatch.setattr(
        rca,
        "ModelResolutionService",
        lambda **kwargs: _resolver(
            _profile("local_quality", ExecutionZone.LOCAL), DataClassification.INTERNAL
        ),
    )
    resources = ExitStack()
    reasoner = rca._create_rca_reasoner(None, object(), owned_resources=resources)
    assert probe.factory_calls == probe.credentials == 0

    class Analysis:
        async def analyze(self, *args):
            return _report(classification=DataClassification.INTERNAL)

    server = rca.create_rca_mcp_server(
        analysis_service=Analysis(), reasoner=reasoner, close_provider=resources.close
    )

    async def call():
        return await server.call_tool(
            "analyze_run", {"run_id": str(RUN_ID), "reasoning": "explain"}
        )

    async def verify():
        lifespan = server.settings.lifespan(server)
        await lifespan.__aenter__()
        calls = [asyncio.create_task(call()) for _ in range(2)]
        shutdown = None
        try:
            await until(probe.factory_started.is_set)
            probe.factory_release.set()
            try:
                await until(lambda: probe.started_calls == 2)
            except TimeoutError:
                pytest.fail(
                    f"RCA provider calls={probe.started_calls}, active={probe.active}, factory={probe.factory_calls}, errors={provider_errors}, completed={[task.done() for task in calls]}"
                )
            assert probe.factory_calls == 1 and probe.active == 2
            for task in calls:
                task.cancel()
            await asyncio.gather(*calls, return_exceptions=True)
            shutdown = asyncio.create_task(lifespan.__aexit__(None, None, None))
            await asyncio.sleep(0)
            assert not shutdown.done() and not probe.adapter._closing
            assert all(not client.close_calls for client in probe.clients)
        finally:
            probe.factory_release.set()
            probe.provider_release.set()
            await asyncio.gather(*calls, return_exceptions=True)
            if shutdown is not None:
                await shutdown
            else:
                await lifespan.__aexit__(None, None, None)
        probe.assert_closed()
        result = await call()
        assert result.structured_content["reasoning"]["status"] == "unavailable"
        assert probe.factory_calls == 1

    try:
        asyncio.run(verify())
    finally:
        resources.close()


@pytest.mark.parametrize("construction_fails", [False, True])
def test_secure_rca_composition_transfers_provider_cleanup_to_service_or_cleans_failure(
    monkeypatch, construction_fails
):
    closed = []
    callbacks = []
    monkeypatch.setenv("AGENT_RUNTIME_DATABASE_URL", "synthetic-no-db")
    monkeypatch.setattr(rca, "PostgreSqlSessionFactory", lambda _: object())
    monkeypatch.setattr(
        rca, "_create_observability_evidence_service", lambda _: object()
    )
    monkeypatch.setattr(rca, "_create_langfuse_evidence_adapter", lambda: None)

    def reasoner(*args, owned_resources):
        owned_resources.callback(lambda: closed.append("provider"))

    monkeypatch.setattr(rca, "_create_rca_reasoner", reasoner)
    sentinel = object()

    def server(*args):
        callbacks.append(args[-1])
        if construction_fails:
            raise RuntimeError("Synthetic server construction failure")
        return sentinel

    monkeypatch.setattr(rca, "_create_secure_rca_server", server)
    if construction_fails:
        with pytest.raises(RuntimeError, match="Synthetic server construction failure"):
            rca.create_secure_rca_mcp_server()
    else:
        assert rca.create_secure_rca_mcp_server() is sentinel
        assert closed == []
        callbacks[0]()
        callbacks[0]()
    assert closed == ["provider"]

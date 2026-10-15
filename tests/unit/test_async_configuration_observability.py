"""Allowed synchronous persistence/backend I/O must leave async services responsive."""

import asyncio
from threading import Lock, get_ident
from types import SimpleNamespace
from uuid import uuid4

import anyio
import httpx
import pytest
from test_c01_async_io import _Gate, _while_blocked
from test_openai_compatible_llm_client import create_configuration

from industrial_ai_agent.agent.model_egress import ModelExecutionAuthorizer
from industrial_ai_agent.agent.model_selection import AGENT_CONSUMER
from industrial_ai_agent.application.model_configuration import (
    ModelConfigurationService,
)
from industrial_ai_agent.domain.security import DataClassification
from industrial_ai_agent.infrastructure.api.app import create_app
from industrial_ai_agent.infrastructure.api.demo_security import (
    BearerTokenSecurityContextResolver,
)
from industrial_ai_agent.infrastructure.api.run_store import InMemoryAgentRunStore
from industrial_ai_agent.infrastructure.observability_mcp_server import (
    create_observability_mcp_server,
)

ASSIGNMENT = {
    "consumer_id": "agent",
    "data_classification": "PUBLIC",
    "selection_mode": "MANUAL",
    "model_id": "local_quality",
}
ADMIN = {"Authorization": "Bearer synthetic-async-configuration"}


class Assignments:
    def __init__(self, gate, blocked):
        self.gate, self.blocked = gate, blocked

    def list(self):
        if self.blocked == "list":
            try:
                self.gate.block()
            finally:
                self.gate.finished.set()
        return ()

    def upsert(self, assignment):
        if self.blocked == "upsert":
            try:
                self.gate.block()
            finally:
                self.gate.finished.set()
        return assignment


def app_for(assignments):
    return create_app(
        object(),
        run_store=InMemoryAgentRunStore(),
        model_configuration_service=ModelConfigurationService(
            catalog=create_configuration(),
            assignments=assignments,
            supported_consumers=(AGENT_CONSUMER,),
            authorizer=ModelExecutionAuthorizer(),
        ),
        security_context_resolver=BearerTokenSecurityContextResolver.from_environment(
            {"AGENT_API_MODEL_ADMIN_TOKEN": "synthetic-async-configuration"}
        ),
    )


@pytest.mark.parametrize(
    "method,blocked", [("GET", "list"), ("PUT", "list"), ("PUT", "upsert")]
)
def test_configuration_io_allows_unrelated_health_progress(method, blocked):
    gate = _Gate()
    app = app_for(Assignments(gate, blocked))

    async def verify():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://fixture"
        ) as client:
            responses = []

            async def request():
                responses.append(
                    await client.request(
                        method,
                        "/api/v1/model-assignments",
                        headers=ADMIN,
                        **({"json": ASSIGNMENT} if method == "PUT" else {}),
                    )
                )

            health = await _while_blocked(
                request(), gate, lambda: client.get("/health")
            )
            assert health.status_code == 200
            assert [r.status_code for r in responses] == [200]

    asyncio.run(verify())
    assert gate.calls == 1


@pytest.mark.parametrize("method", ["GET", "PUT"])
def test_configuration_denial_happens_before_repository_io(method):
    gate = _Gate()
    app = app_for(Assignments(gate, "list"))

    async def verify():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://fixture"
        ) as client:
            response = await client.request(
                method,
                "/api/v1/model-assignments",
                **({"json": ASSIGNMENT} if method == "PUT" else {}),
            )
            assert response.status_code == 403

    asyncio.run(verify())
    assert gate.calls == 0


class Evidence:
    def __init__(self, gate):
        self.gate = gate

    def block(self):
        try:
            self.gate.block()
            return {"status": "synthetic"}
        finally:
            self.gate.finished.set()

    def get_run_trace(self, _identifier):
        return SimpleNamespace(model_dump=lambda **_: self.block())

    def get_trace_logs(self, *_args):
        self.block()
        return ()

    get_run_metrics = get_run_trace

    def investigate_run(self, _identifier):
        return self.block()


@pytest.mark.parametrize(
    "tool,argument",
    [
        ("get_run_trace", "run_id"),
        ("get_trace_logs", "trace_id"),
        ("get_run_metrics", "run_or_trace_id"),
        ("investigate_run", "run_id"),
    ],
)
def test_allowed_observability_io_does_not_block_mcp_progress(tool, argument):
    gate = _Gate()

    async def verify():
        run_id = uuid4()
        trace_id = "0123456789abcdef0123456789abcdef"
        store = InMemoryAgentRunStore()
        await store.create(run_id, data_classification=DataClassification.INTERNAL)
        server = create_observability_mcp_server(
            evidence_service=Evidence(gate),
            store_for_context=lambda _: store,
            trace_run_ids={trace_id: run_id},
        )
        value = trace_id if argument == "trace_id" else str(run_id)
        tools = await _while_blocked(
            server.call_tool(tool, {argument: value}), gate, server.list_tools
        )
        assert tool in {t.name for t in tools}

    asyncio.run(verify())
    assert gate.calls == 1


def test_configuration_worker_capacity_stays_bounded_during_slow_reads():
    gate = _Gate()
    lock = Lock()
    active = peak = calls = 0
    threads = set()

    class SlowAssignments:
        def list(self):
            nonlocal active, peak, calls
            with lock:
                active += 1
                calls += 1
                peak = max(peak, active)
                threads.add(get_ident())
                if active == 2:
                    gate.started.set()
            try:
                assert gate.release.wait(5), "Worker release missing"
                return ()
            finally:
                with lock:
                    active -= 1

    async def verify():
        limiter = anyio.to_thread.current_default_thread_limiter()
        previous = limiter.total_tokens
        limiter.total_tokens = 2
        tasks = []
        try:
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app_for(SlowAssignments())),
                base_url="http://fixture",
            ) as client:
                tasks = [
                    asyncio.create_task(
                        client.get("/api/v1/model-assignments", headers=ADMIN)
                    )
                    for _ in range(6)
                ]
                assert await asyncio.to_thread(gate.started.wait, 3)
                assert (await client.get("/health")).status_code == 200
                assert peak == 2 and limiter.borrowed_tokens == 2
                assert not any(task.done() for task in tasks)
                gate.release.set()
                assert all(r.status_code == 200 for r in await asyncio.gather(*tasks))
                assert limiter.borrowed_tokens == 0
        finally:
            gate.release.set()
            await asyncio.gather(*tasks, return_exceptions=True)
            limiter.total_tokens = previous

    loop_thread = get_ident()
    asyncio.run(verify())
    assert calls == 6 and peak == 2 and active == 0
    assert loop_thread not in threads


def test_configuration_write_stays_owned_when_request_scope_is_cancelled():
    gate = _Gate()
    completed = []

    async def verify():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app_for(Assignments(gate, "upsert"))),
            base_url="http://fixture",
        ) as client:
            with anyio.CancelScope() as scope:
                async with anyio.create_task_group() as group:

                    async def write():
                        await client.put(
                            "/api/v1/model-assignments", headers=ADMIN, json=ASSIGNMENT
                        )
                        completed.append(True)

                    group.start_soon(write)
                    try:
                        assert await anyio.to_thread.run_sync(gate.started.wait, 3)
                        scope.cancel()
                        with anyio.CancelScope(shield=True):
                            assert not gate.finished.is_set()
                            assert (await client.get("/health")).status_code == 200
                    finally:
                        gate.release.set()
            assert gate.finished.is_set()
            # The HTTP response may be cancelled after the owned write completes.
            assert completed == []
            assert anyio.to_thread.current_default_thread_limiter().borrowed_tokens == 0

    anyio.run(verify)
    assert gate.calls == 1

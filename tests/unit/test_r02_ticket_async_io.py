"""Owned off-loop protected ticket persistence; all side effects are synthetic."""

import asyncio
import subprocess
import sys
from contextvars import ContextVar
from textwrap import dedent
from threading import Event, Lock, get_ident
from time import perf_counter, sleep
from uuid import UUID, uuid4

import anyio
import pytest
from mcp.server.mcpserver.exceptions import ToolError

from industrial_ai_agent.domain.security import DataClassification, SecurityContext
from industrial_ai_agent.infrastructure.action_approval import (
    AgentRunStoreActionApprovalPort,
)
from industrial_ai_agent.infrastructure.api.run_store import InMemoryAgentRunStore
from industrial_ai_agent.infrastructure.factory_mcp_server import (
    create_default_factory_mcp_server,
)
from industrial_ai_agent.infrastructure.in_memory_maintenance_ticket_repository import (
    InMemoryMaintenanceTicketRepository,
)
from industrial_ai_agent.tools.maintenance_ticket import MaintenanceTicketCapability

CONTEXT = SecurityContext(
    "synthetic-r02", ("test",), DataClassification.CONFIDENTIAL, True
)
SUMMARY = "Synthetic R02 action"
TRACE = ContextVar("synthetic_r02_trace", default=None)


def test_capability_standalone_import_does_not_depend_on_mcp_initializing_anyio():
    code = dedent("""
        import asyncio
        from uuid import uuid4
        from industrial_ai_agent.domain.security import DataClassification, SecurityContext
        from industrial_ai_agent.infrastructure.in_memory_maintenance_ticket_repository import InMemoryMaintenanceTicketRepository
        from industrial_ai_agent.tools.maintenance_ticket import MaintenanceTicketCapability
        class Claims:
            async def claim_approved_action(self, *args):
                return True
        repository = InMemoryMaintenanceTicketRepository()
        capability = MaintenanceTicketCapability(repository, approval_claims=Claims())
        context = SecurityContext('synthetic', ('test',), DataClassification.CONFIDENTIAL, True)
        result = asyncio.run(capability.create_maintenance_ticket(str(uuid4()), 'S04', 'Synthetic standalone', run_id=uuid4(), security_context=context))
        assert result.station_id == 'S04' and len(repository.tickets) == 1
    """)
    completed = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr


class ControlledRepository(InMemoryMaintenanceTicketRepository):
    def __init__(self, *, delay=0, blocked=False, error=False):
        super().__init__()
        self.delay = delay
        self.error = error
        self.started = Event()
        self.release = Event()
        if not blocked:
            self.release.set()
        self.lock = Lock()
        self.calls = 0
        self.reads = 0
        self.active = 0
        self.peak = 0
        self.threads = set()
        self.contexts = []
        self.block_reads = False

    def _io(self):
        with self.lock:
            self.active += 1
            self.peak = max(self.peak, self.active)
            self.threads.add(get_ident())
            self.contexts.append(TRACE.get())
        self.started.set()
        try:
            if not self.release.wait(5):
                raise TimeoutError("Synthetic repository release missing")
            sleep(self.delay)
            if self.error:
                raise RuntimeError("SYNTHETIC DATABASE PRIVATE DETAIL")
        finally:
            with self.lock:
                self.active -= 1

    def create_maintenance_ticket(self, *args):
        self.calls += 1
        self._io()
        with self.lock:
            return super().create_maintenance_ticket(*args)

    def get_maintenance_ticket_by_request_id(self, *args):
        self.reads += 1
        if self.block_reads:
            self._io()
        return super().get_maintenance_ticket_by_request_id(*args)


class RecordingClaims(AgentRunStoreActionApprovalPort):
    def __init__(self, store):
        super().__init__(lambda _: store)
        self.calls = self.successes = 0

    async def claim_approved_action(self, claim, context):
        self.calls += 1
        result = await super().claim_approved_action(claim, context)
        self.successes += int(result)
        return result


async def pending(store, run_id, *, approve=True, station="S04"):
    proposal = await store.wait_for_approval(
        run_id,
        {
            "action": "create_maintenance_ticket",
            "action_id": "reused-model-id",
            "arguments": {"station_id": station, "summary": SUMMARY},
        },
    )
    identity = proposal.approval_request["approval_execution_id"]
    if approve:
        assert await store.claim_resume(
            run_id,
            approval_execution_id=UUID(identity),
            decision="approve",
            approval_clearance=CONTEXT.clearance,
        )
    return identity


async def setup(repository=None, claims_type=RecordingClaims):
    store = InMemoryAgentRunStore()
    run_id = uuid4()
    await store.create(run_id)
    identity = await pending(store, run_id)
    repository = repository or ControlledRepository()
    claims = claims_type(store)
    capability = MaintenanceTicketCapability(repository, approval_claims=claims)
    return store, run_id, identity, repository, claims, capability


async def execute(capability, run_id, identity, **kwargs):
    return await capability.create_maintenance_ticket(
        identity,
        kwargs.pop("station", "S04"),
        SUMMARY,
        run_id=run_id,
        security_context=kwargs.pop("context", CONTEXT),
        **kwargs,
    )


async def until(predicate):
    async with asyncio.timeout(3):
        while not predicate():
            await asyncio.sleep(0.002)


def test_slow_write_keeps_heartbeat_and_unrelated_health_responsive():
    async def verify():
        _, run_id, identity, repository, claims, capability = await setup(
            ControlledRepository(delay=0.2)
        )
        loop_thread = get_ident()

        async def heartbeat():
            started = perf_counter()
            await asyncio.sleep(0.02)
            return perf_counter() - started

        ticker = asyncio.create_task(heartbeat())
        task = asyncio.create_task(execute(capability, run_id, identity))
        try:
            await until(repository.started.is_set)
            assert await ticker < 0.15
            assert not task.done()
            assert (
                await asyncio.wait_for(asyncio.sleep(0, result="healthy"), 0.1)
                == "healthy"
            )
            await task
        finally:
            repository.release.set()
            await asyncio.gather(task, ticker, return_exceptions=True)
        assert loop_thread not in repository.threads
        assert repository.calls == claims.successes == len(repository.tickets) == 1

    asyncio.run(verify())


def test_create_cannot_begin_before_authoritative_claim_succeeds():
    async def verify():
        entered, release = asyncio.Event(), asyncio.Event()

        class DelayedClaims(RecordingClaims):
            async def claim_approved_action(self, *args):
                entered.set()
                await release.wait()
                return await super().claim_approved_action(*args)

        _, run_id, identity, repository, claims, capability = await setup(
            claims_type=DelayedClaims
        )
        task = asyncio.create_task(execute(capability, run_id, identity))
        try:
            await asyncio.wait_for(entered.wait(), 2)
            assert not repository.started.is_set()
            assert repository.calls == claims.successes == 0
        finally:
            release.set()
            await task
        assert repository.calls == claims.successes == 1

    asyncio.run(verify())


@pytest.mark.parametrize(
    "denial",
    [
        "missing-port",
        "clearance",
        "wrong-generation",
        "wrong-target",
        "pending",
        "stale",
    ],
)
def test_invalid_or_missing_authoritative_approval_creates_nothing(denial):
    async def verify():
        store, run_id, identity, repository, _, capability = await setup()
        kwargs = {}
        if denial == "missing-port":
            capability = MaintenanceTicketCapability(repository)
        elif denial == "clearance":
            kwargs["context"] = SecurityContext(
                "public", ("test",), DataClassification.PUBLIC, True
            )
        elif denial == "wrong-generation":
            identity = str(uuid4())
        elif denial == "wrong-target":
            kwargs["station"] = "S02"
        else:
            new = await pending(store, run_id, approve=False, station="S02")
            if denial == "pending":
                identity = new
                kwargs["station"] = "S02"
        with pytest.raises(PermissionError):
            await execute(capability, run_id, identity, **kwargs)
        assert repository.calls == len(repository.tickets) == 0

    asyncio.run(verify())


def test_same_generation_replay_returns_persisted_ticket_without_second_create():
    async def verify():
        _, run_id, identity, repository, claims, capability = await setup()
        first = await execute(capability, run_id, identity)
        assert await execute(capability, run_id, identity) == first
        assert repository.calls == claims.successes == len(repository.tickets) == 1
        assert repository.reads == 1

    asyncio.run(verify())


def test_concurrent_same_generation_never_dispatches_a_second_write():
    async def verify():
        _, run_id, identity, repository, claims, capability = await setup(
            ControlledRepository(blocked=True)
        )
        first = asyncio.create_task(execute(capability, run_id, identity))
        try:
            await until(repository.started.is_set)
            with pytest.raises(PermissionError):
                await execute(capability, run_id, identity)
            assert repository.calls == 1
        finally:
            repository.release.set()
            result = await first
        assert await execute(capability, run_id, identity) == result
        assert repository.calls == claims.successes == len(repository.tickets) == 1

    asyncio.run(verify())


def test_distinct_approved_generations_with_same_model_action_id_remain_independent():
    async def verify():
        store, run_id, identity, repository, claims, capability = await setup()
        a = await execute(capability, run_id, identity)
        next_identity = await pending(store, run_id, station="S02")
        b = await execute(capability, run_id, next_identity, station="S02")
        assert a.ticket_id != b.ticket_id and identity != next_identity
        assert repository.calls == claims.successes == len(repository.tickets) == 2

    asyncio.run(verify())


def test_pending_cancellation_before_claim_does_not_consume_or_write():
    async def verify():
        _, run_id, identity, repository, claims, capability = await setup()

        async def cancelled_caller():
            asyncio.current_task().cancel()
            await execute(capability, run_id, identity)

        with pytest.raises(asyncio.CancelledError):
            await asyncio.create_task(cancelled_caller())
        assert claims.calls == repository.calls == 0

    asyncio.run(verify())


def test_cancellation_after_claim_before_dispatch_leaves_consumed_generation_fail_closed():
    async def verify():
        class CancelAfterClaim(RecordingClaims):
            async def claim_approved_action(self, *args):
                result = await super().claim_approved_action(*args)
                asyncio.current_task().cancel()
                return result

        store, run_id, identity, repository, claims, capability = await setup(
            claims_type=CancelAfterClaim
        )
        with pytest.raises(asyncio.CancelledError):
            await asyncio.create_task(execute(capability, run_id, identity))
        assert claims.successes == 1 and repository.calls == 0
        safe = MaintenanceTicketCapability(
            repository, approval_claims=RecordingClaims(store)
        )
        with pytest.raises(PermissionError):
            await execute(safe, run_id, identity)
        assert repository.calls == 0

    asyncio.run(verify())


@pytest.mark.parametrize("late_error", [False, True])
def test_native_cancellation_during_create_drains_worker_and_recovers_only_committed_result(
    late_error,
):
    async def verify():
        _, run_id, identity, repository, claims, capability = await setup(
            ControlledRepository(blocked=True, error=late_error)
        )
        limiter = anyio.to_thread.current_default_thread_limiter()
        task = asyncio.create_task(execute(capability, run_id, identity))
        try:
            await until(repository.started.is_set)
            task.cancel()
            await asyncio.sleep(0.02)
            task.cancel()
            await asyncio.sleep(0.02)
            assert not task.done()
            assert repository.active == limiter.borrowed_tokens == 1
            assert await asyncio.wait_for(asyncio.sleep(0, result=True), 0.1)
            assert repository.calls == claims.successes == 1
        finally:
            repository.release.set()
            with pytest.raises(asyncio.CancelledError):
                await task
        assert repository.active == limiter.borrowed_tokens == 0
        assert not any(
            t.get_name() == "maintenance-ticket-owned-io" for t in asyncio.all_tasks()
        )
        if late_error:
            with pytest.raises(PermissionError):
                await execute(capability, run_id, identity)
        else:
            result = await execute(capability, run_id, identity)
            assert result.ticket_id == repository.tickets[0].ticket_id
        assert repository.calls == 1 and len(repository.tickets) <= 1

    asyncio.run(verify())


def test_anyio_scope_cancellation_drains_owned_create_before_scope_exits():
    async def verify():
        _, run_id, identity, repository, _, capability = await setup(
            ControlledRepository(blocked=True)
        )
        ready = asyncio.Event()
        scopes = []

        async def caller():
            with anyio.CancelScope() as scope:
                scopes.append(scope)
                ready.set()
                await execute(capability, run_id, identity)
            assert scope.cancelled_caught

        task = asyncio.create_task(caller())
        try:
            await ready.wait()
            await until(repository.started.is_set)
            scopes[0].cancel()
            await asyncio.sleep(0.02)
            assert not task.done() and repository.active == 1
        finally:
            repository.release.set()
            await task
        assert repository.calls == len(repository.tickets) == 1
        assert anyio.to_thread.current_default_thread_limiter().borrowed_tokens == 0

    asyncio.run(verify())


def test_outer_timeout_waits_for_commit_instead_of_abandoning_or_retrying_write():
    async def verify():
        _, run_id, identity, repository, _, capability = await setup(
            ControlledRepository(blocked=True)
        )

        async def caller():
            async with asyncio.timeout(0.05):
                return await execute(capability, run_id, identity)

        task = asyncio.create_task(caller())
        try:
            await until(repository.started.is_set)
            await asyncio.sleep(0.08)
            assert not task.done() and repository.active == 1
        finally:
            repository.release.set()
            with pytest.raises(TimeoutError):
                await task
        assert await execute(capability, run_id, identity)
        assert repository.calls == len(repository.tickets) == 1

    asyncio.run(verify())


def test_cancellation_queued_for_pool_capacity_skips_repository_dispatch():
    async def verify():
        _, run_id, identity, repository, claims, capability = await setup()
        limiter = anyio.to_thread.current_default_thread_limiter()
        limiter.total_tokens = 1
        occupied, release = Event(), Event()

        def occupy():
            occupied.set()
            assert release.wait(5)

        blocker = asyncio.create_task(anyio.to_thread.run_sync(occupy))
        task = None
        try:
            await until(occupied.is_set)
            task = asyncio.create_task(execute(capability, run_id, identity))
            await until(lambda: limiter.statistics().tasks_waiting == 1)
            assert claims.successes == 1
            task.cancel()
            await asyncio.sleep(0.02)
            assert repository.calls == 0 and not task.done()
        finally:
            release.set()
            await blocker
            if task is not None:
                with pytest.raises(asyncio.CancelledError):
                    await task
        assert (
            repository.calls == len(repository.tickets) == limiter.borrowed_tokens == 0
        )

    asyncio.run(verify())


def test_parallel_slow_reads_and_writes_share_bounded_worker_capacity():
    async def verify():
        _, run_id, identity, repository, _, capability = await setup()
        original = await execute(capability, run_id, identity)
        repository.release.clear()
        repository.block_reads = True
        limiter = anyio.to_thread.current_default_thread_limiter()
        limiter.total_tokens = 2
        calls = [execute(capability, run_id, identity) for _ in range(4)]
        for _ in range(4):
            _, other_run, other_id, _, _, other_capability = await setup(repository)
            calls.append(execute(other_capability, other_run, other_id))
        tasks = [asyncio.create_task(call) for call in calls]
        try:
            await until(
                lambda: (
                    repository.active == 2 and limiter.statistics().tasks_waiting == 6
                )
            )
            assert limiter.borrowed_tokens == 2 and repository.peak == 2
            assert (
                await asyncio.wait_for(asyncio.sleep(0.02, result="healthy"), 0.15)
                == "healthy"
            )
        finally:
            repository.release.set()
            results = await asyncio.gather(*tasks)
        assert all(result == original for result in results[:4])
        assert repository.peak == 2 and len(repository.threads) <= 2
        assert len(repository.tickets) == repository.calls == 5
        assert repository.active == limiter.borrowed_tokens == 0

    asyncio.run(verify())


def test_worker_propagates_trace_context_without_moving_security_or_session_objects():
    async def verify():
        _, run_id, identity, repository, _, capability = await setup()
        token = TRACE.set("synthetic-trace-only")
        try:
            await execute(capability, run_id, identity)
        finally:
            TRACE.reset(token)
        assert repository.contexts == ["synthetic-trace-only"]

    asyncio.run(verify())


def test_repository_error_propagates_without_success_or_automatic_retry():
    async def verify():
        _, run_id, identity, repository, claims, capability = await setup(
            ControlledRepository(delay=0.2, error=True)
        )
        task = asyncio.create_task(execute(capability, run_id, identity))
        await until(repository.started.is_set)
        assert await asyncio.wait_for(asyncio.sleep(0.02, result=True), 0.15)
        with pytest.raises(RuntimeError, match="SYNTHETIC DATABASE"):
            await task
        with pytest.raises(PermissionError):
            await execute(capability, run_id, identity)
        assert (
            repository.calls == claims.successes == 1 and len(repository.tickets) == 0
        )
        assert anyio.to_thread.current_default_thread_limiter().borrowed_tokens == 0

    asyncio.run(verify())


def test_factory_mcp_normalizes_repository_failure_without_database_details(
    monkeypatch,
):
    from industrial_ai_agent.infrastructure import factory_mcp_server as factory

    async def verify():
        _, run_id, identity, repository, _, capability = await setup(
            ControlledRepository(error=True)
        )
        monkeypatch.delenv("FACTORY_DATABASE_URL", raising=False)
        monkeypatch.setattr(
            factory, "MaintenanceTicketCapability", lambda *args: capability
        )
        server = create_default_factory_mcp_server()
        with pytest.raises(
            ToolError, match="Error executing tool create_maintenance_ticket"
        ) as error:
            await server.call_tool(
                "create_maintenance_ticket",
                {
                    "station_id": "S04",
                    "summary": SUMMARY,
                    "request_id": identity,
                    "run_id": str(run_id),
                },
            )
        assert "PRIVATE DETAIL" not in str(error.value)
        assert repository.calls == 1 and len(repository.tickets) == 0

    asyncio.run(verify())


def test_real_in_memory_repository_serializes_parallel_worker_id_allocation(
    monkeypatch,
):
    from industrial_ai_agent.infrastructure import (
        in_memory_maintenance_ticket_repository as memory,
    )

    entered, release = Event(), Event()
    constructor = memory.MaintenanceTicket
    calls = []

    def controlled_constructor(**kwargs):
        calls.append(kwargs["request_id"])
        if len(calls) == 1:
            entered.set()
            assert release.wait(5)
        return constructor(**kwargs)

    monkeypatch.setattr(memory, "MaintenanceTicket", controlled_constructor)

    async def verify():
        repository = memory.InMemoryMaintenanceTicketRepository()
        _, run_a, id_a, _, _, cap_a = await setup(repository)
        _, run_b, id_b, _, _, cap_b = await setup(repository)
        task_a = asyncio.create_task(execute(cap_a, run_a, id_a))
        task_b = None
        try:
            await until(entered.is_set)
            task_b = asyncio.create_task(execute(cap_b, run_b, id_b))
            await asyncio.sleep(0.04)
            assert len(calls) == 1
        finally:
            release.set()
            results = await asyncio.gather(task_a, *([task_b] if task_b else []))
        assert len(calls) == len(repository.tickets) == 2
        assert results[0].ticket_id != results[1].ticket_id

    asyncio.run(verify())


def test_cancellation_after_commit_before_response_recovers_existing_result_without_retry():
    committed, respond = Event(), Event()

    class CommitBeforeResponse(ControlledRepository):
        def create_maintenance_ticket(self, *args):
            result = super().create_maintenance_ticket(*args)
            committed.set()
            assert respond.wait(5)
            return result

    async def verify():
        _, run_id, identity, repository, claims, capability = await setup(
            CommitBeforeResponse()
        )
        task = asyncio.create_task(execute(capability, run_id, identity))
        try:
            await until(committed.is_set)
            task.cancel()
            await asyncio.sleep(0.02)
            assert not task.done()
            result = await execute(capability, run_id, identity)
            assert result.ticket_id == repository.tickets[0].ticket_id
            assert repository.calls == claims.successes == len(repository.tickets) == 1
        finally:
            respond.set()
            with pytest.raises(asyncio.CancelledError):
                await task
        assert anyio.to_thread.current_default_thread_limiter().borrowed_tokens == 0

    asyncio.run(verify())

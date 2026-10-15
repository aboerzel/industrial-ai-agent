"""Real synchronous ticket transactions through owned async I/O in an isolated DB."""

import asyncio
import os
from contextlib import contextmanager
from hashlib import sha256
from threading import Event, get_ident
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.engine import make_url

from industrial_ai_agent.domain.security import DataClassification, SecurityContext
from industrial_ai_agent.infrastructure.action_approval import (
    AgentRunStoreActionApprovalPort,
)
from industrial_ai_agent.infrastructure.api.postgres_run_store import (
    PostgreSqlAgentRunStore,
)
from industrial_ai_agent.infrastructure.persistence.postgres import (
    PostgreSqlMaintenanceTicketRepository,
    PostgreSqlSessionFactory,
)
from industrial_ai_agent.tools.maintenance_ticket import MaintenanceTicketCapability

DATABASE_URL = os.getenv("FACTORY_DATABASE_URL")
CONTEXT = SecurityContext(
    "synthetic-r02-db", ("test",), DataClassification.CONFIDENTIAL, True
)
pytestmark = pytest.mark.skipif(
    not DATABASE_URL, reason="requires disposable local PostgreSQL"
)


@pytest.mark.parametrize("cancel_during_create", [False, True])
def test_postgres_owned_ticket_create_replay_unique_constraint_and_thread_lifetime(
    cancel_during_create,
):
    url = make_url(DATABASE_URL)
    if url.host not in {"127.0.0.1", "localhost"} or not url.database.startswith(
        "verification_"
    ):
        pytest.skip("R02 writes require the isolated verification database")
    loop_thread = get_ident()
    sessions = []

    class TrackingSessions(PostgreSqlSessionFactory):
        @contextmanager
        def session(self, context):
            owner = get_ident()
            assert owner != loop_thread
            try:
                with super().session(context) as session:
                    yield session
            finally:
                assert get_ident() == owner
                sessions.append(owner)

    started, release = Event(), Event()

    class RecordingRepository(PostgreSqlMaintenanceTicketRepository):
        calls = 0

        def create_maintenance_ticket(self, *args):
            assert get_ident() != loop_thread
            self.calls += 1
            started.set()
            assert release.wait(5)
            return super().create_maintenance_ticket(*args)

        def get_maintenance_ticket_by_request_id(self, *args):
            assert get_ident() != loop_thread
            return super().get_maintenance_ticket_by_request_id(*args)

    factory = TrackingSessions(DATABASE_URL)
    store = PostgreSqlAgentRunStore(factory, CONTEXT)
    repository = RecordingRepository(factory, CONTEXT)
    capability = MaintenanceTicketCapability(
        repository, approval_claims=AgentRunStoreActionApprovalPort(lambda _: store)
    )

    async def verify():
        run_id = uuid4()
        summary = "Synthetic isolated R02 database action"
        await store.create(run_id)
        proposal = await store.wait_for_approval(
            run_id,
            {
                "action": "create_maintenance_ticket",
                "action_id": "reused-model-id",
                "arguments": {"station_id": "S04", "summary": summary},
            },
        )
        identity = proposal.approval_request["approval_execution_id"]
        assert await store.claim_resume(
            run_id,
            approval_execution_id=UUID(identity),
            decision="approve",
            approval_clearance=CONTEXT.clearance,
        )

        async def execute():
            return await capability.create_maintenance_ticket(
                identity, "S04", summary, run_id=run_id, security_context=CONTEXT
            )

        task = asyncio.create_task(execute())
        try:
            async with asyncio.timeout(3):
                while not started.is_set():
                    await asyncio.sleep(0.002)
            # The consumed claim cannot create a second ticket while the first is pending.
            with pytest.raises(PermissionError):
                await execute()
            if cancel_during_create:
                task.cancel()
                await asyncio.sleep(0.02)
                assert not task.done()
            assert (
                await asyncio.wait_for(asyncio.sleep(0, result="healthy"), 0.1)
                == "healthy"
            )
        finally:
            release.set()
            if cancel_during_create:
                with pytest.raises(asyncio.CancelledError):
                    await task
            else:
                await task
        recovered = await execute()
        assert await execute() == recovered
        assert repository.calls == 1
        key = sha256(f"{run_id}:{identity}".encode()).hexdigest()

        def persisted_rows():
            with factory.session(CONTEXT) as session:
                rows = session.scalar(
                    text(
                        "SELECT count(*) FROM maintenance_ticket WHERE request_id=:key"
                    ),
                    {"key": key},
                )
                index = session.scalar(
                    text(
                        "SELECT indexdef FROM pg_indexes WHERE indexname='maintenance_ticket_request_id_key'"
                    )
                )
                return rows, index

        rows, index = await asyncio.to_thread(persisted_rows)
        assert rows == 1 and "UNIQUE INDEX" in index
        assert recovered.station_id == "S04" and recovered.summary == summary
        assert sessions and loop_thread not in sessions

    try:
        asyncio.run(verify())
    finally:
        release.set()
        factory.dispose()

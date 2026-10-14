"""C06 durability and row-lock claims in an explicitly disposable PostgreSQL DB."""

import asyncio
import os
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from sqlalchemy import MetaData, Table, create_engine, insert, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError

from industrial_ai_agent.agent.response_language import ResponseLanguage
from industrial_ai_agent.agent.run_classification_policy import AgentRunProfile
from industrial_ai_agent.application.action_approval import (
    MaintenanceTicketApprovalClaim,
)
from industrial_ai_agent.domain.product_history import StationId
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
    "synthetic-c06-db", ("test",), DataClassification.CONFIDENTIAL, True
)
pytestmark = pytest.mark.skipif(
    not DATABASE_URL, reason="requires disposable local PostgreSQL"
)


@pytest.fixture
def persisted():
    url = make_url(DATABASE_URL)
    if url.host not in {"127.0.0.1", "localhost"} or not url.database.startswith(
        "verification_"
    ):
        pytest.skip("C06 writes require the isolated verification database")
    factory = PostgreSqlSessionFactory(DATABASE_URL)
    store = PostgreSqlAgentRunStore(factory, CONTEXT)
    repository = PostgreSqlMaintenanceTicketRepository(factory, CONTEXT)
    capability = MaintenanceTicketCapability(
        repository, approval_claims=AgentRunStoreActionApprovalPort(lambda _: store)
    )
    try:
        yield factory, store, repository, capability
    finally:
        factory.dispose()


def _proposal(station="S04", summary="Synthetic first action"):
    return {
        "action": "create_maintenance_ticket",
        "action_id": "reused-model-call",
        "arguments": {"station_id": station, "summary": summary},
    }


async def _approve(
    store, run_id, station="S04", summary="Synthetic first action", **kwargs
):
    pending = await store.wait_for_approval(
        run_id, _proposal(station, summary), **kwargs
    )
    assert (
        await store.claim_resume(
            run_id,
            decision="approve",
            approval_clearance=DataClassification.CONFIDENTIAL,
        )
        is not None
    )
    return pending.approval_request["approval_execution_id"]


async def _execute(
    capability, run_id, identity, station="S04", summary="Synthetic first action"
):
    return await capability.create_maintenance_ticket(
        identity, station, summary, run_id=run_id, security_context=CONTEXT
    )


@pytest.mark.parametrize(
    "station,summary",
    [
        ("S02", "Synthetic second action"),
        ("S04", "Synthetic second action"),
        ("S04", "Synthetic first action"),
    ],
)
def test_persistent_generations_with_reused_model_id_remain_distinct(
    persisted, station, summary
):
    _, store, _, capability = persisted

    async def verify():
        run_id = uuid4()
        await store.create(run_id)
        first = await _approve(store, run_id)
        result_a = await _execute(capability, run_id, first)
        second = await _approve(store, run_id, station, summary)
        result_b = await _execute(capability, run_id, second, station, summary)
        assert UUID(first) != UUID(second)
        assert result_a.ticket_id != result_b.ticket_id
        assert (result_b.station_id, result_b.summary) == (station, summary)
        assert await _execute(capability, run_id, first) == result_a

    asyncio.run(verify())


def test_recreated_store_and_repository_keep_the_exact_generation(persisted):
    _, store, _, _ = persisted

    async def verify():
        run_id = uuid4()
        await store.create(run_id)
        identity = await _approve(store, run_id)
        recreated_factory = PostgreSqlSessionFactory(DATABASE_URL)
        try:
            recreated_store = PostgreSqlAgentRunStore(recreated_factory, CONTEXT)
            restored = await recreated_store.get(run_id)
            assert restored.approval_request["approval_execution_id"] == identity
            repository = PostgreSqlMaintenanceTicketRepository(
                recreated_factory, CONTEXT
            )
            capability = MaintenanceTicketCapability(
                repository,
                approval_claims=AgentRunStoreActionApprovalPort(
                    lambda _: recreated_store
                ),
            )
            first = await _execute(capability, run_id, identity)
            assert await _execute(capability, run_id, identity) == first
            assert (await recreated_store.get(run_id)).approval_generations[identity][
                "consumed"
            ] is True
        finally:
            recreated_factory.dispose()

    asyncio.run(verify())


def test_database_row_lock_consumes_a_generation_exactly_once(persisted):
    factory, store, _, capability = persisted

    async def verify():
        run_id = uuid4()
        await store.create(run_id)
        identity = await _approve(store, run_id)
        claim = MaintenanceTicketApprovalClaim(
            run_id, identity, StationId("S04"), "Synthetic first action"
        )
        independent = PostgreSqlAgentRunStore(factory, CONTEXT)
        results = await asyncio.gather(
            *(
                selected.claim_protected_action_approval(
                    claim, security_context=CONTEXT
                )
                for selected in (store, independent, store, independent)
            )
        )
        assert results.count(True) == 1
        assert results.count(False) == 3
        # Claim success alone must not allow a second write if the first has not committed.
        with pytest.raises(PermissionError):
            await _execute(capability, run_id, identity)

    asyncio.run(verify())


def test_distinct_persistent_generations_can_finish_concurrently(persisted):
    factory, store, repository, capability_b = persisted

    async def verify():
        run_id = uuid4()
        await store.create(run_id)
        first = await _approve(store, run_id)
        claimed = asyncio.Event()
        release = asyncio.Event()

        class WaitingClaims(AgentRunStoreActionApprovalPort):
            async def claim_approved_action(self, claim, security_context):
                result = await super().claim_approved_action(claim, security_context)
                if result:
                    claimed.set()
                    await release.wait()
                return result

        independent = PostgreSqlAgentRunStore(factory, CONTEXT)
        capability_a = MaintenanceTicketCapability(
            repository, approval_claims=WaitingClaims(lambda _: independent)
        )
        task = asyncio.create_task(_execute(capability_a, run_id, first))
        try:
            await asyncio.wait_for(claimed.wait(), timeout=5)
            second = await _approve(store, run_id, "S02", "Synthetic second action")
            result_b = await _execute(
                capability_b, run_id, second, "S02", "Synthetic second action"
            )
        finally:
            release.set()
            result_a = await task
        assert result_a.ticket_id != result_b.ticket_id
        assert (result_a.station_id, result_b.station_id) == ("S04", "S02")

    asyncio.run(verify())


def test_persistent_wrong_generation_and_target_do_not_consume_approval(persisted):
    _, store, _, capability = persisted

    async def verify():
        run_id = uuid4()
        await store.create(run_id)
        identity = await _approve(store, run_id)
        for wrong_id, station in ((str(uuid4()), "S04"), (identity, "S02")):
            with pytest.raises(PermissionError):
                await _execute(capability, run_id, wrong_id, station)
        assert (await store.get(run_id)).approval_generations[identity][
            "consumed"
        ] is False
        await _execute(capability, run_id, identity)

    asyncio.run(verify())


def test_upgrade_from_previous_head_preserves_but_does_not_authorize_legacy(
    persisted, monkeypatch
):
    from alembic import command
    from alembic.config import Config

    parent_admin = make_url(os.environ["FACTORY_DATABASE_ADMIN_URL"])
    assert parent_admin.host in {"127.0.0.1", "localhost"}
    database = "c06_migration_" + uuid4().hex
    maintenance = create_engine(
        parent_admin.set(database="postgres"), isolation_level="AUTOCOMMIT"
    )
    created = False
    try:
        with maintenance.connect() as connection:
            connection.execute(text(f'CREATE DATABASE "{database}"'))
        created = True
        admin = parent_admin.set(database=database)
        monkeypatch.setenv(
            "FACTORY_DATABASE_ADMIN_URL", admin.render_as_string(hide_password=False)
        )
        setup = create_engine(admin)
        with setup.begin() as connection:
            connection.execute(
                text("GRANT USAGE, CREATE ON SCHEMA public TO factory_migration_owner")
            )
        command.upgrade(Config("alembic.ini"), "0024_agent_run_approval_clearance")
        run_id = uuid4()
        legacy = _proposal()
        with setup.begin() as connection:
            table = Table(
                "agent_runs",
                MetaData(),
                schema="agent_runtime",
                autoload_with=connection,
            )
            connection.execute(
                insert(table).values(
                    run_id=run_id,
                    thread_id=run_id,
                    investigation_id=run_id,
                    investigation_sequence=1,
                    status="running",
                    data_classification=int(DataClassification.CONFIDENTIAL),
                    run_profile=AgentRunProfile.CONFIDENTIAL_TROUBLESHOOTING.value,
                    request_text="Synthetic legacy approval",
                    response_language=ResponseLanguage.EN.value,
                    approval_payload=legacy,
                    approval_action="create_maintenance_ticket",
                    approval_decision="approve",
                    approval_requested_at=datetime.now(UTC),
                    approval_decided_at=datetime.now(UTC),
                    approval_decided_clearance="CONFIDENTIAL",
                )
            )
        command.upgrade(Config("alembic.ini"), "head")
        app = make_url(DATABASE_URL).set(database=database)
        factory = PostgreSqlSessionFactory(app.render_as_string(hide_password=False))
        try:
            store = PostgreSqlAgentRunStore(factory, CONTEXT)
            record = asyncio.run(store.get(run_id))
            assert record.approval_request == legacy
            assert record.approval_generations == {}
            claim = MaintenanceTicketApprovalClaim(
                run_id, "reused-model-call", StationId("S04"), "Synthetic first action"
            )
            assert (
                asyncio.run(
                    store.claim_protected_action_approval(
                        claim, security_context=CONTEXT
                    )
                )
                is False
            )
            assert (
                asyncio.run(
                    store.is_consumed_protected_action_approval(
                        claim, security_context=CONTEXT
                    )
                )
                is False
            )
        finally:
            factory.dispose()
            setup.dispose()
    finally:
        if created:
            assert database.startswith("c06_migration_") and len(database) == 46
            with maintenance.connect() as connection:
                connection.execute(
                    text(
                        "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname=:database AND pid<>pg_backend_pid()"
                    ),
                    {"database": database},
                )
                connection.execute(text(f'DROP DATABASE "{database}"'))
        maintenance.dispose()


def test_fresh_head_history_is_empty_and_database_rejects_non_object_history(persisted):
    factory, store, _, _ = persisted
    run_id = uuid4()
    created = asyncio.run(store.create(run_id))
    assert created.approval_generations == {}
    with pytest.raises(IntegrityError), factory.session(CONTEXT) as session:
        session.execute(
            text(
                "UPDATE agent_runtime.agent_runs SET approval_generations='[]'::json WHERE run_id=:run"
            ),
            {"run": run_id},
        )
    assert asyncio.run(store.get(run_id)).approval_generations == {}

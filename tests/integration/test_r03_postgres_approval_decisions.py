"""Durable exact-generation decisions and PostgreSQL row-lock races; no actions."""

import asyncio
import os
from uuid import UUID, uuid4

import pytest
from sqlalchemy.engine import make_url

from industrial_ai_agent.domain.security import DataClassification, SecurityContext
from industrial_ai_agent.infrastructure.api.postgres_run_store import (
    PostgreSqlAgentRunStore,
)
from industrial_ai_agent.infrastructure.api.schemas import RunStatus
from industrial_ai_agent.infrastructure.persistence.postgres import (
    PostgreSqlSessionFactory,
)

CONTEXT = SecurityContext(
    "synthetic-r03-db", ("test",), DataClassification.CONFIDENTIAL, True
)


@pytest.fixture
def database():
    database_url = os.getenv("FACTORY_DATABASE_URL")
    if not database_url:
        pytest.skip("requires disposable local PostgreSQL")
    url = make_url(database_url)
    if url.host not in {"127.0.0.1", "localhost"} or not url.database.startswith(
        "verification_"
    ):
        pytest.skip("R03 writes require an isolated verification database")
    return database_url


def proposal(station):
    return {
        "action": "create_maintenance_ticket",
        "action_id": "reused-model-action-id",
        "arguments": {"station_id": station, "summary": "Synthetic R03 approval"},
    }


async def claim(store, run_id, token, decision="approve"):
    return await store.claim_resume(
        run_id,
        approval_execution_id=UUID(token),
        decision=decision,
        approval_clearance=DataClassification.CONFIDENTIAL,
    )


@pytest.mark.parametrize("decision", ["approve", "reject"])
def test_postgres_recreated_store_rejects_stale_and_accepts_current_generation(
    database, decision
):
    run_id = uuid4()
    first_sessions = PostgreSqlSessionFactory(database)
    first = PostgreSqlAgentRunStore(first_sessions, CONTEXT)

    async def persist():
        await first.create(run_id)
        a = (await first.wait_for_approval(run_id, proposal("S04"))).approval_request[
            "approval_execution_id"
        ]
        assert await claim(first, run_id, a) is not None
        b = (await first.wait_for_approval(run_id, proposal("S02"))).approval_request[
            "approval_execution_id"
        ]
        return a, b

    try:
        a, b = asyncio.run(persist())
    finally:
        first_sessions.dispose()
    assert a != b
    second_sessions = PostgreSqlSessionFactory(database)
    second = PostgreSqlAgentRunStore(second_sessions, CONTEXT)

    async def resumed():
        before = await second.get(run_id)
        for invalid in [None, "invalid", b]:
            assert (
                await second.claim_resume(
                    run_id,
                    approval_execution_id=invalid,
                    decision=decision,
                    approval_clearance=DataClassification.CONFIDENTIAL,
                )
                is None
            )
        assert await claim(second, run_id, a, decision) is None
        assert await claim(second, run_id, str(uuid4()), decision) is None
        after = await second.get(run_id)
        assert after == before
        assert after.status is RunStatus.WAITING_FOR_APPROVAL
        assert after.approval_generations[b]["decision"] is None
        assert not after.approval_generations[b]["consumed"]
        assert await claim(second, run_id, b, decision) is not None
        assert (await second.get(run_id)).approval_generations[b][
            "decision"
        ] == decision

    try:
        asyncio.run(resumed())
    finally:
        second_sessions.dispose()


def test_postgres_current_token_survives_runtime_restart(database):
    run_id = uuid4()
    sessions = PostgreSqlSessionFactory(database)
    store = PostgreSqlAgentRunStore(sessions, CONTEXT)

    async def persist():
        await store.create(run_id)
        return (
            await store.wait_for_approval(run_id, proposal("S04"))
        ).approval_request["approval_execution_id"]

    try:
        a = asyncio.run(persist())
    finally:
        sessions.dispose()
    restored_sessions = PostgreSqlSessionFactory(database)
    restored = PostgreSqlAgentRunStore(restored_sessions, CONTEXT)
    try:
        assert asyncio.run(claim(restored, run_id, a)) is not None
    finally:
        restored_sessions.dispose()


@pytest.mark.parametrize("mode", ["approve-reject", "duplicate", "stale-current"])
def test_postgres_atomic_generation_claim_races(database, mode):
    sessions = PostgreSqlSessionFactory(database)
    store = PostgreSqlAgentRunStore(sessions, CONTEXT)
    other_sessions = PostgreSqlSessionFactory(database)
    other = PostgreSqlAgentRunStore(other_sessions, CONTEXT)

    async def race():
        run_id = uuid4()
        await store.create(run_id)
        a = (await store.wait_for_approval(run_id, proposal("S04"))).approval_request[
            "approval_execution_id"
        ]
        b = a
        if mode == "stale-current":
            assert await claim(store, run_id, a) is not None
            b = (
                await store.wait_for_approval(run_id, proposal("S02"))
            ).approval_request["approval_execution_id"]
        results = await asyncio.gather(
            claim(store, run_id, a),
            claim(
                other, run_id, b, "reject" if mode == "approve-reject" else "approve"
            ),
        )
        assert sum(result is not None for result in results) == 1
        if mode == "stale-current":
            assert results[0] is None and results[1] is not None
        after = await store.get(run_id)
        assert not after.approval_generations[b]["consumed"]

    try:
        asyncio.run(race())
    finally:
        sessions.dispose()
        other_sessions.dispose()

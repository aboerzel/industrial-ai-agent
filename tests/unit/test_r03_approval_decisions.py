"""Bind human intent to the displayed generation without executing any action."""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from industrial_ai_agent.agent.agent_run import AgentRunResult, AgentRunStatus
from industrial_ai_agent.agent.troubleshooting_run_service import RunExecution
from industrial_ai_agent.domain.security import DataClassification
from industrial_ai_agent.infrastructure.api.app import create_app
from industrial_ai_agent.infrastructure.api.demo_security import (
    BearerTokenSecurityContextResolver,
)
from industrial_ai_agent.infrastructure.api.demo_sessions import DemoSessions
from industrial_ai_agent.infrastructure.api.run_store import InMemoryAgentRunStore
from industrial_ai_agent.infrastructure.api.schemas import RunStatus


def proposal(station):
    return {
        "action": "create_maintenance_ticket",
        "action_id": "reused-model-action-id",
        "arguments": {"station_id": station, "summary": "Synthetic review action"},
        "summary": f"Synthetic approval for {station}",
        "classification": "CONFIDENTIAL",
        "model_id": "local_quality",
        "status": "waiting_for_approval",
        "created_at": datetime.now(UTC).isoformat(),
    }


class NoActions:
    persistent_hitl_enabled = True

    def __init__(self):
        self.calls = 0

    async def resume(self, **kwargs):
        self.calls += 1
        return RunExecution(
            result=AgentRunResult(
                status=AgentRunStatus.SUCCESS,
                final_answer="Synthetic completion without side effects",
                tool_call_count=0,
            )
        )


@pytest.fixture
def api():
    store, service = InMemoryAgentRunStore(), NoActions()
    app = create_app(
        service,
        run_store=store,
        security_context_resolver=BearerTokenSecurityContextResolver.from_environment(
            {"MCP_INDUSTRIAL_AGENT_TOKEN": "synthetic-r03-fixture"}
        ),
        demo_sessions=DemoSessions(),
    )
    with TestClient(
        app, headers={"Authorization": "Bearer synthetic-r03-fixture"}
    ) as client:
        yield client, store, service


def pending(api):
    client, store, _ = api
    run_id = uuid4()

    async def setup():
        await store.create(run_id, model_profile="local_quality")
        return await store.wait_for_approval(run_id, proposal("S04"))

    record = client.portal.call(setup)
    return run_id, record.approval_request["approval_execution_id"]


def post(client, run_id, token, decision="approve", clearance="CONFIDENTIAL"):
    return client.post(
        f"/api/v1/runs/{run_id}/resume",
        json={
            "decision": decision,
            "approval_execution_id": token,
            "user_clearance": clearance,
        },
    )


def advance(api, run_id, token):
    client, store, _ = api

    async def change():
        claimed = await store.claim_resume(
            run_id,
            approval_execution_id=UUID(token),
            decision="approve",
            approval_clearance=DataClassification.CONFIDENTIAL,
        )
        assert claimed is not None
        return await store.wait_for_approval(run_id, proposal("S02"))

    return client.portal.call(change).approval_request["approval_execution_id"]


def unchanged(api, run_id, token):
    client, store, service = api
    record = client.portal.call(store.get, run_id)
    assert record.status is RunStatus.WAITING_FOR_APPROVAL
    assert record.approval_request["approval_execution_id"] == token
    assert record.approval_decision is None
    assert record.approval_generations[token]["decision"] is None
    assert not record.approval_generations[token]["consumed"]
    return service.calls


@pytest.mark.parametrize("decision", ["approve", "reject"])
def test_stale_human_decision_cannot_affect_new_generation_with_reused_model_id(
    api, decision
):
    client, _, _ = api
    run_id, a = pending(api)
    shown = client.get(f"/api/v1/runs/{run_id}?user_clearance=CONFIDENTIAL")
    assert shown.status_code == 200
    public = shown.json()["approval_request"]
    assert public["approval_execution_id"] == a
    assert set(public) == {
        "approval_execution_id",
        "action",
        "arguments",
        "summary",
        "classification",
        "model_id",
        "status",
        "created_at",
    }
    b = advance(api, run_id, a)
    assert a != b
    response = post(client, run_id, a, decision)
    assert response.status_code == 409
    assert "S02" not in response.text
    assert unchanged(api, run_id, b) == 0


@pytest.mark.parametrize("decision", ["approve", "reject"])
def test_current_human_decision_is_accepted(api, decision):
    client, store, service = api
    run_id, a = pending(api)
    b = advance(api, run_id, a)
    assert post(client, run_id, b, decision).status_code == 200
    assert (
        client.portal.call(store.get, run_id).approval_generations[b]["decision"]
        == decision
    )
    assert service.calls == 1


@pytest.mark.parametrize(
    "payload,expected",
    [
        ({"decision": "approve"}, 422),
        ({"decision": "approve", "approval_execution_id": None}, 422),
        ({"decision": "approve", "approval_execution_id": "not-a-uuid"}, 422),
        ({"decision": "approve", "approval_execution_id": str(uuid4())}, 409),
    ],
)
def test_invalid_or_missing_generation_fails_closed(api, payload, expected):
    client, _, _ = api
    run_id, a = pending(api)
    assert (
        client.post(
            f"/api/v1/runs/{run_id}/resume",
            json={**payload, "user_clearance": "CONFIDENTIAL"},
        ).status_code
        == expected
    )
    assert unchanged(api, run_id, a) == 0


def test_successful_old_decision_replay_does_not_approve_new_generation(api):
    client, store, service = api
    run_id, a = pending(api)
    assert post(client, run_id, a).status_code == 200
    b = client.portal.call(
        store.wait_for_approval, run_id, proposal("S02")
    ).approval_request["approval_execution_id"]
    assert post(client, run_id, a).status_code == 409
    assert unchanged(api, run_id, b) == service.calls == 1


@pytest.mark.parametrize("mode", ["approve-reject", "duplicate", "stale-current"])
def test_atomic_generation_claim_races(api, mode):
    client, store, _ = api
    run_id, a = pending(api)
    b = advance(api, run_id, a) if mode == "stale-current" else a

    async def race():
        return await asyncio.gather(
            *(
                store.claim_resume(
                    run_id,
                    approval_execution_id=UUID(token),
                    decision=decision,
                    approval_clearance=DataClassification.CONFIDENTIAL,
                )
                for token, decision in [
                    (a, "approve"),
                    (b, "reject" if mode == "approve-reject" else "approve"),
                ]
            )
        )

    results = client.portal.call(race)
    assert sum(value is not None for value in results) == 1
    if mode == "stale-current":
        assert results[0] is None and results[1] is not None
    record = client.portal.call(store.get, run_id)
    assert not record.approval_generations[b]["consumed"]


def test_valid_generation_does_not_bypass_visibility(api):
    client, _, _ = api
    run_id, a = pending(api)
    response = post(client, run_id, a, clearance="PUBLIC")
    assert response.status_code == 404
    assert response.json()["code"] == "run_not_found"
    assert a not in response.text
    assert unchanged(api, run_id, a) == 0


@pytest.mark.parametrize("mode", ["approve-reject", "duplicate", "stale-current"])
def test_concurrent_http_decisions_only_resume_the_bound_generation_once(api, mode):
    client, store, service = api
    run_id, a = pending(api)
    b = advance(api, run_id, a) if mode == "stale-current" else a
    with ThreadPoolExecutor(max_workers=2) as workers:
        first = workers.submit(post, client, run_id, a)
        second = workers.submit(
            post, client, run_id, b, "reject" if mode == "approve-reject" else "approve"
        )
        results = [first.result(), second.result()]
    assert sorted(response.status_code for response in results) == [200, 409]
    if mode == "stale-current":
        assert results[0].status_code == 409
    assert service.calls == 1
    record = client.portal.call(store.get, run_id)
    assert not record.approval_generations[b]["consumed"]


def test_direct_store_rejects_untyped_generation_without_mutation(api):
    client, store, _ = api
    run_id, a = pending(api)

    async def invalid_claims():
        for invalid in [None, "invalid", a]:
            assert (
                await store.claim_resume(
                    run_id,
                    approval_execution_id=invalid,
                    decision="approve",
                    approval_clearance=DataClassification.CONFIDENTIAL,
                )
                is None
            )

    client.portal.call(invalid_claims)
    assert unchanged(api, run_id, a) == 0


def test_identity_switch_preserved_request_obeys_authorization_and_generation(api):
    client, _, _ = api
    run_id, a = pending(api)
    b = advance(api, run_id, a)
    client.headers.pop("Authorization")
    client.headers["X-Demo-Session"] = "1"
    for username, expected in [("demo-public", 404), ("demo-restricted", 409)]:
        switched = client.post("/api/v1/auth/switch", json={"username": username})
        assert switched.status_code == 200
        response = client.post(
            f"/api/v1/runs/{run_id}/resume",
            json={"decision": "approve", "approval_execution_id": a},
        )
        assert response.status_code == expected
        assert unchanged(api, run_id, b) == 0

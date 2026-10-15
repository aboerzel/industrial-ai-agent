"""Complete seeded RLS inventory reaches the real agent, durable API result and reload."""

import os

import pytest
from fastapi.testclient import TestClient
from fc03_discovery_support import expected_ids, fixture_app, product_ids

from industrial_ai_agent.infrastructure.api.demo_sessions import DemoSessions

pytestmark = pytest.mark.skipif(
    not os.getenv("FACTORY_DATABASE_URL"),
    reason="requires disposable seeded PostgreSQL",
)


@pytest.mark.parametrize("username", tuple(DemoSessions().users))
@pytest.mark.parametrize("language", ("DE", "EN"))
@pytest.mark.parametrize("mode", ("fallback", "sparse", "invented"))
def test_complete_authorized_products_independent_of_model_and_reference_budget(
    username, language, mode
):
    app, service, _, factory = fixture_app(model_mode=mode, durable=True)
    expected = expected_ids(DemoSessions().users[username].security_context().clearance)
    try:
        with TestClient(app, headers={"X-Demo-Session": "1"}) as client:
            client.post(
                "/api/v1/auth/switch", json={"username": username}
            ).raise_for_status()
            response = client.post(
                "/api/v1/runs",
                json={
                    "message": "Welche Produkte kennst du?"
                    if language == "DE"
                    else "Which products do you know?",
                    "response_language": language,
                },
            )
            assert response.status_code == 200, response.text
            api = response.json()
            assert api["status"] == "success"
            trace = service.traces[-1]
            assert trace["bypass_rls"] is False
            for stage in (
                "database_ids",
                "repository_ids",
                "factory_mcp_ids",
                "agent_raw_ids",
                "tool_message_ids",
                "model_input_ids",
                "public_projection_ids",
            ):
                assert trace[stage] == expected, stage
                assert len(trace[stage]) == len(set(trace[stage]))
            assert product_ids(api["answer"]) == expected
            assert len(api["identifiers"]) <= 12
            assert all(
                reference["value"] != "P9999" for reference in api["identifiers"]
            )
            assert (
                trace["effective_classification"]
                >= trace["factory_mcp"]["classification"]
            )
            assert [item["tool"] for item in api["tool_calls"]] == ["list_products"]
            # This GET reconstructs the stored result using the PostgreSQL adapter.
            persisted = client.get(f"/api/v1/runs/{api['run_id']}")
            assert persisted.status_code == 200
            assert product_ids(persisted.json()["answer"]) == expected
            assert persisted.json()["answer"] == api["answer"]
            rows = [
                line.split(":")[0][2:]
                for line in api["answer"].splitlines()
                if line.startswith("- ")
            ]
            assert rows == expected
            for row in trace["factory_mcp"]["products"]:
                if row["latest_status"]:
                    assert (
                        f"{row['product_id']}: {row['latest_status']}" in api["answer"]
                    )
    finally:
        factory.dispose()

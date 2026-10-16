"""SD-01 through SD-15: authorized station inventory survives model omissions."""

import json
import os

import pytest
from fastapi.testclient import TestClient
from fc03_discovery_support import STATION_LEVELS, fixture_app, station_ids

from industrial_ai_agent.infrastructure.api.demo_sessions import DemoSessions

pytestmark = pytest.mark.skipif(
    not os.getenv("FACTORY_DATABASE_URL"),
    reason="requires disposable seeded PostgreSQL",
)


@pytest.mark.parametrize("username", tuple(DemoSessions().users))
@pytest.mark.parametrize("language", ("DE", "EN"))
@pytest.mark.parametrize("mode", ("sparse", "invented", "fallback"))
def test_complete_stations_from_rls_to_durable_api_despite_model(
    username, language, mode, record_property
):
    app, service, _, factory = fixture_app(model_mode=mode, durable=True)
    clearance = DemoSessions().users[username].clearance
    expected = sorted(
        item for level in STATION_LEVELS[: int(clearance) + 1] for item in level
    )
    try:
        with TestClient(app, headers={"X-Demo-Session": "1"}) as client:
            client.post(
                "/api/v1/auth/switch", json={"username": username}
            ).raise_for_status()
            response = client.post(
                "/api/v1/runs",
                json={
                    "message": "welche stationen kennst du"
                    if language == "DE"
                    else "Which stations do you know?",
                    "response_language": language,
                },
            )
            assert response.status_code == 200
            body = response.json()
            trace = service.traces[-1]
            persisted = client.get(f"/api/v1/runs/{body['run_id']}").json()
            record_property(
                "station_pipeline",
                json.dumps(
                    {
                        "username": username,
                        "language": language,
                        "trace": trace,
                        "api": body,
                        "persisted": persisted,
                    }
                ),
            )
            assert trace["bypass_rls"] is False
            for stage in (
                "database_ids",
                "repository_ids",
                "factory_mcp_ids",
                "agent_raw_ids",
                "tool_message_ids",
                "model_input_ids",
                "reference_ids",
            ):
                assert trace[stage] == expected, stage
            assert trace["model_output_ids"] != expected
            assert body["status"] == "success"
            assert station_ids(body["answer"]) == expected
            assert persisted["answer"] == body["answer"]
            assert station_ids(trace["agent_result"]["final_answer"]) == expected
            assert len(body["identifiers"]) <= 12
            assert "S99" not in body["answer"]
            assert [call["tool"] for call in body["tool_calls"]] == ["list_stations"]
            rows = [
                line.split(":")[0][2:]
                for line in body["answer"].splitlines()
                if line.startswith("- ")
            ]
            assert rows == expected
            for station in trace["factory_mcp"]["stations"]:
                assert f"{station['station_id']}: {station['name']}" in body["answer"]
                if station["state"] is not None:
                    assert station["state"] in body["answer"]
    finally:
        factory.dispose()

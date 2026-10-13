"""API smoke authentication/status contracts; no process, network, or model calls."""

from types import ModuleType

import httpx
import pytest

from scripts import smoke_test_fastapi, smoke_test_persistent_hitl_api


@pytest.fixture(params=[smoke_test_fastapi, smoke_test_persistent_hitl_api])
def smoke(request: pytest.FixtureRequest) -> ModuleType:
    return request.param


def test_smoke_sends_existing_confidential_bearer_token(
    smoke: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MCP_INDUSTRIAL_AGENT_TOKEN", "synthetic-smoke-token")
    calls = []

    def respond(request: httpx.Request) -> httpx.Response:
        calls.append(request.headers.get("Authorization"))
        return httpx.Response(
            200 if calls[-1] == "Bearer synthetic-smoke-token" else 403
        )

    with httpx.Client(
        headers=smoke._api_headers(), transport=httpx.MockTransport(respond)
    ) as client:
        smoke._expect_status(client.get("http://fixture/api/v1/runs/fixture"), 200)
    assert calls == ["Bearer synthetic-smoke-token"]


@pytest.mark.parametrize("status", [401, 403, 404, 500, 201, 302])
def test_smoke_rejects_every_unexpected_status_without_credentials(
    smoke: ModuleType, status: int
) -> None:
    with pytest.raises(RuntimeError, match=f"HTTP status {status}") as error:
        smoke._expect_status(httpx.Response(status, text="synthetic-secret"), 200)
    assert "synthetic-secret" not in str(error.value)


def test_smoke_accepts_only_explicit_negative_status(smoke: ModuleType) -> None:
    smoke._expect_status(httpx.Response(409), 409)
    for status in (200, 403, 500):
        with pytest.raises(RuntimeError):
            smoke._expect_status(httpx.Response(status), 409)


def test_missing_token_stops_smoke_before_any_side_effect(
    smoke: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MCP_INDUSTRIAL_AGENT_TOKEN", "")
    monkeypatch.setattr(smoke, "load_local_environment", lambda *_: None)
    if smoke is smoke_test_persistent_hitl_api:
        monkeypatch.setattr("sys.argv", ["smoke", "--decision", "reject"])

    def forbidden(*args, **kwargs):
        pytest.fail("A missing token must not start processes or query domain state")

    monkeypatch.setattr(smoke.subprocess, "Popen", forbidden)
    if smoke is smoke_test_persistent_hitl_api:
        monkeypatch.setattr(smoke, "_ticket_count", forbidden)
    with pytest.raises(RuntimeError, match="MCP_INDUSTRIAL_AGENT_TOKEN is required"):
        smoke.main()

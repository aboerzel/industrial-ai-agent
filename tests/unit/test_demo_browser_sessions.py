# DEMO-ONLY CREDENTIALS — NOT FOR PRODUCTION OR SERVICE AUTHENTICATION
"""Server-side demo identity authorization; no provider, network or hardware calls."""

import time

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from industrial_ai_agent.agent.agent_run import AgentRunResult, AgentRunStatus
from industrial_ai_agent.agent.run_classification_policy import (
    AgentRunClassificationPolicy,
    AgentRunProfile,
)
from industrial_ai_agent.application.document_content import AuthorizedDocumentContent
from industrial_ai_agent.domain.security import DataClassification
from industrial_ai_agent.infrastructure.api.app import create_app
from industrial_ai_agent.infrastructure.api.demo_security import (
    BearerTokenSecurityContextResolver,
)
from industrial_ai_agent.infrastructure.api.demo_sessions import (
    COOKIE_NAME,
    DemoSessions,
)
from industrial_ai_agent.infrastructure.api.run_store import InMemoryAgentRunStore


class Documents:
    def get_document(self, document_id, context):
        if context.clearance < DataClassification[document_id]:
            return None
        return AuthorizedDocumentContent(b"synthetic", "text/plain", "document.txt")


class NoModels:
    async def run_with_policy(self, *args, **kwargs):
        raise AssertionError("No model invocation permitted")


class ModelConfiguration:
    def list_models(self):
        return ()

    def list_assignments(self):
        return ()


def client(
    *,
    enabled=True,
    documents=None,
    sessions=None,
    run_service=None,
    run_store_factory=None,
):
    return TestClient(
        create_app(
            run_service or NoModels(),
            run_store=None if run_store_factory else InMemoryAgentRunStore(),
            run_store_factory=run_store_factory,
            security_context_resolver=BearerTokenSecurityContextResolver.from_environment(
                {
                    "MCP_INDUSTRIAL_AGENT_PUBLIC_TOKEN": "synthetic-service-token",
                }
            ),
            demo_sessions=(sessions or DemoSessions()) if enabled else None,
            document_content_reader=documents or Documents(),
            model_configuration_service=ModelConfiguration(),
        ),
        headers={"X-Demo-Session": "1"},
    )


@pytest.mark.parametrize("username", tuple(DemoSessions().users))
def test_all_demo_users_have_authoritative_clearance_and_orthogonal_admin_role(
    username,
):
    with client() as browser:
        response = browser.post("/api/v1/auth/switch", json={"username": username})
        assert response.status_code == 200
        expected = DemoSessions().users[username]
        assert response.json() == expected.metadata()
        assert browser.get("/api/v1/auth/me").json() == expected.metadata()
        for classification in DataClassification:
            for suffix in ("", "/download"):
                resource = browser.get(
                    f"/api/v1/documents/{classification.name}{suffix}"
                )
                assert resource.status_code == (
                    200 if expected.clearance >= classification else 404
                )
        for route in ("models", "model-assignments"):
            assert browser.get(f"/api/v1/{route}").status_code == (
                200 if "MODEL_ADMIN" in expected.roles else 403
            )
        assert (
            browser.get(
                "/api/v1/documents/RESTRICTED?user_clearance=RESTRICTED"
            ).status_code
            == 422
        )
        assert (
            browser.post(
                "/api/v1/runs",
                json={"message": "synthetic", "user_clearance": "RESTRICTED"},
            ).status_code
            == 422
        )


def test_bootstrap_login_switch_logout_and_previous_cookie_revocation():
    with client() as browser:
        assert browser.get("/api/v1/auth/me").status_code == 401
        response = browser.post("/api/v1/auth/bootstrap", json={})
        assert response.json()["username"] == "demo-public"
        cookie = browser.cookies.get(COOKIE_NAME)
        assert "HttpOnly" in response.headers["set-cookie"]
        assert "SameSite=strict" in response.headers["set-cookie"]
        assert "www-authenticate" not in response.headers
        assert (
            browser.post(
                "/api/v1/auth/login",
                json={"username": "demo-admin", "password": "incorrect"},
            ).status_code
            == 401
        )
        assert browser.get("/api/v1/auth/me").json()["username"] == "demo-public"
        assert (
            browser.post(
                "/api/v1/auth/login",
                json={"username": "demo-admin", "password": "demo-admin"},
            ).status_code
            == 200
        )
        assert (
            browser.get(
                "/api/v1/auth/me", headers={"Cookie": f"{COOKIE_NAME}={cookie}"}
            ).status_code
            == 401
        )
        assert browser.post("/api/v1/auth/logout", json={}).status_code == 200
        assert browser.get("/api/v1/models").status_code == 401
        assert browser.post("/api/v1/auth/bootstrap", json={}).status_code == 401
        assert (
            browser.post(
                "/api/v1/auth/switch", json={"username": "demo-internal"}
            ).status_code
            == 200
        )
        assert browser.get("/api/v1/auth/me").json()["username"] == "demo-internal"


def test_disabled_mode_has_no_demo_sessions_or_quick_switch():
    with client(enabled=False) as browser:
        assert browser.get("/api/v1/auth/config").json() == {
            "demo_mode": False,
            "users": [],
        }
        for route in ("bootstrap", "switch", "login", "logout"):
            assert (
                browser.post(
                    f"/api/v1/auth/{route}", json={"username": "demo-admin"}
                ).status_code
                == 404
            )
        assert browser.get("/api/v1/documents/PUBLIC").status_code == 403


def test_cross_origin_session_mutations_and_arbitrary_identity_claims_fail_closed():
    with client() as browser:
        assert (
            browser.post(
                "/api/v1/auth/switch",
                json={"username": "demo-admin"},
                headers={"Origin": "https://untrusted.invalid"},
            ).status_code
            == 403
        )
        assert (
            browser.post(
                "/api/v1/auth/switch",
                json={"username": "demo-admin", "clearance": "RESTRICTED"},
            ).status_code
            == 422
        )
        assert (
            browser.post(
                "/api/v1/auth/switch", json={"username": "unconfigured"}
            ).status_code
            == 401
        )
        assert browser.post("/api/v1/auth/bootstrap", json={}).status_code == 200
        browser.headers.pop("X-Demo-Session")
        assert browser.post("/api/v1/auth/logout", json={}).status_code == 403
        assert browser.get("/api/v1/auth/me").json()["username"] == "demo-public"


def test_session_capacity_and_expiry_are_bounded(monkeypatch):
    clock = [100.0]
    monkeypatch.setattr(time, "monotonic", lambda: clock[0])
    sessions = DemoSessions(ttl_seconds=10, capacity=1)
    token = sessions.establish("demo-public", None)
    with pytest.raises(HTTPException) as error:
        sessions.establish("demo-admin", None)
    assert error.value.status_code == 429
    clock[0] += 11
    assert sessions.resolve(token) is None
    assert (
        sessions.resolve(sessions.establish("demo-admin", None)).clearance
        is DataClassification.PUBLIC
    )


def test_demo_configuration_never_returns_passwords_tokens_or_service_credentials():
    with client() as browser:
        response = browser.get("/api/v1/auth/config")
        assert response.headers["Cache-Control"] == "no-store"
        for user in response.json()["users"]:
            assert set(user) == {"username", "clearance", "roles"}
        assert "synthetic-service-token" not in response.text


def test_invalid_login_payload_never_echoes_accidentally_submitted_secret():
    with client() as browser:
        private_input = "synthetic-private-input-" * 20
        response = browser.post(
            "/api/v1/auth/login",
            json={"username": "demo-admin", "password": private_input},
        )
        assert response.status_code == 422
        assert private_input not in response.text
        assert (
            browser.post(
                "/api/v1/auth/login",
                json={"username": "demo-admin", "password": "ungültig"},
            ).status_code
            == 401
        )


def test_canonical_admin_has_public_clearance_and_restricted_has_no_admin_role():
    sessions = DemoSessions()
    assert sessions.users["demo-admin"].metadata() == {
        "username": "demo-admin",
        "clearance": "PUBLIC",
        "roles": ["MODEL_ADMIN"],
    }
    assert sessions.users["demo-restricted"].metadata() == {
        "username": "demo-restricted",
        "clearance": "RESTRICTED",
        "roles": [],
    }


@pytest.mark.parametrize("username", ["demo-public", "demo-admin"])
def test_public_clearance_cannot_reach_structured_internal_diagnostic_lookup(username):
    with client() as browser:
        assert (
            browser.post("/api/v1/auth/switch", json={"username": username}).status_code
            == 200
        )
        assert (
            browser.post(
                "/api/v1/diagnostics", json={"product_id": "P4900", "station_id": "S02"}
            ).status_code
            == 403
        )


@pytest.mark.parametrize(
    "username", ["demo-internal", "demo-confidential", "demo-restricted"]
)
def test_authorized_diagnostic_retains_its_server_owned_internal_database_scope(
    username,
):
    contexts = []
    store = InMemoryAgentRunStore()

    def store_factory(context):
        contexts.append(context)
        return store

    class Diagnostic:
        async def resolve_internal_diagnostic(self, target):
            assert target.product_id == "P4900"
            assert target.station_id == "S02"
            return AgentRunClassificationPolicy().resolve(
                AgentRunProfile.INTERNAL_DIAGNOSTIC
            )

        async def run_with_policy(self, *args, **kwargs):
            return AgentRunResult(
                status=AgentRunStatus.SUCCESS,
                final_answer="Synthetic internal result",
                tool_call_count=0,
            )

    with client(run_service=Diagnostic(), run_store_factory=store_factory) as browser:
        assert (
            browser.post("/api/v1/auth/switch", json={"username": username}).status_code
            == 200
        )
        response = browser.post(
            "/api/v1/diagnostics", json={"product_id": "P4900", "station_id": "S02"}
        )
        assert response.status_code == 200
        assert response.json()["data_classification"] == "INTERNAL"
        assert contexts and all(
            context.clearance is DataClassification.INTERNAL for context in contexts
        )
        assert all(context.subject_id == username for context in contexts)

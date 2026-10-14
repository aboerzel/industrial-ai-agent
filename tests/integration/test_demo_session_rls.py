"""Real session -> API -> PostgreSQL RLS matrix against disposable demo fixtures."""

import os

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from industrial_ai_agent.agent.agent_run import AgentRunResult, AgentRunStatus
from industrial_ai_agent.application.document_content import AuthorizedDocumentContent
from industrial_ai_agent.domain.security import DataClassification
from industrial_ai_agent.infrastructure.api.app import create_app
from industrial_ai_agent.infrastructure.api.demo_security import (
    BearerTokenSecurityContextResolver,
)
from industrial_ai_agent.infrastructure.api.demo_sessions import DemoSessions
from industrial_ai_agent.infrastructure.api.postgres_run_store import (
    PostgreSqlAgentRunStore,
)
from industrial_ai_agent.infrastructure.api.run_store import InMemoryAgentRunStore
from industrial_ai_agent.infrastructure.persistence.postgres import (
    PostgreSqlSessionFactory,
)

DATABASE_URL = os.getenv("FACTORY_DATABASE_URL")
pytestmark = pytest.mark.skipif(
    not DATABASE_URL, reason="requires disposable PostgreSQL fixtures"
)


class RlsDocumentProbe:
    def __init__(self, factory):
        self.factory = factory

    def get_document(self, document_id, context):
        # No Python clearance filter: the database alone decides row visibility.
        with self.factory.connection(context) as connection:
            row = connection.execute(
                text(
                    "SELECT classification FROM document_catalog "
                    "WHERE classification = :classification LIMIT 1"
                ),
                {"classification": int(DataClassification[document_id])},
            ).first()
        return (
            AuthorizedDocumentContent(b"synthetic RLS proof", "text/plain", "proof.txt")
            if row
            else None
        )


class NoModels:
    async def run_with_policy(self, *args, **kwargs):
        raise AssertionError("No model calls")


class ModelConfig:
    def list_models(self):
        return ()


@pytest.mark.parametrize("username", tuple(DemoSessions().users))
def test_demo_session_clearance_and_role_matrix_reaches_real_postgres_rls(username):
    factory = PostgreSqlSessionFactory(DATABASE_URL)
    app = create_app(
        NoModels(),
        run_store=InMemoryAgentRunStore(),
        demo_sessions=DemoSessions(),
        security_context_resolver=BearerTokenSecurityContextResolver.from_environment(
            {
                "MCP_INDUSTRIAL_AGENT_PUBLIC_TOKEN": "synthetic-service-token",
            }
        ),
        document_content_reader=RlsDocumentProbe(factory),
        model_configuration_service=ModelConfig(),
    )
    try:
        with TestClient(app, headers={"X-Demo-Session": "1"}) as browser:
            assert (
                browser.post(
                    "/api/v1/auth/switch", json={"username": username}
                ).status_code
                == 200
            )
            user = DemoSessions().users[username]
            for classification in DataClassification:
                result = browser.get(
                    f"/api/v1/documents/{classification.name}/download"
                )
                assert result.status_code == (
                    200 if classification <= user.clearance else 404
                )
            assert browser.get("/api/v1/models").status_code == (
                200 if user.roles else 403
            )
    finally:
        factory.dispose()


def test_shared_investigation_visibility_remains_classification_based_with_real_session_rls():
    factory = PostgreSqlSessionFactory(DATABASE_URL)

    class SyntheticService:
        async def run_with_policy(self, *args, **kwargs):
            return AgentRunResult(
                status=AgentRunStatus.SUCCESS,
                final_answer="Synthetic shared classified result",
                tool_call_count=0,
            )

    app = create_app(
        SyntheticService(),
        run_store=None,
        demo_sessions=DemoSessions(),
        run_store_factory=lambda context: PostgreSqlAgentRunStore(factory, context),
        security_context_resolver=BearerTokenSecurityContextResolver.from_environment(
            {
                "MCP_INDUSTRIAL_AGENT_PUBLIC_TOKEN": "synthetic-service-token",
            }
        ),
    )
    try:
        with TestClient(app, headers={"X-Demo-Session": "1"}) as browser:
            browser.post(
                "/api/v1/auth/switch", json={"username": "demo-confidential"}
            ).raise_for_status()
            run = browser.post(
                "/api/v1/runs",
                json={"message": "Investigate P4711.", "response_language": "EN"},
            )
            assert run.status_code == 200
            assert run.json()["data_classification"] == "CONFIDENTIAL"
            investigation_id = run.json()["investigation_id"]
            for username, expected in [
                ("demo-restricted", 200),
                ("demo-public", 404),
                ("demo-admin", 404),
            ]:
                browser.post(
                    "/api/v1/auth/switch", json={"username": username}
                ).raise_for_status()
                for suffix in ("", "/pdf"):
                    assert (
                        browser.get(
                            f"/api/v1/investigations/{investigation_id}{suffix}"
                        ).status_code
                        == expected
                    )
    finally:
        factory.dispose()

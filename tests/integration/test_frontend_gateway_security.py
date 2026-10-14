# DEMO-ONLY CREDENTIALS — NOT FOR PRODUCTION OR SERVICE AUTHENTICATION
"""Real Nginx -> FastAPI authorization; isolated synthetic records, no model calls.

Requires the locally installed nginx:1.29-alpine Docker image. No production data,
MCP service, database, provider, or existing container is modified.
"""

import secrets
import socket
import subprocess
import threading
import time
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
import uvicorn

from industrial_ai_agent.agent.llm import ModelId
from industrial_ai_agent.agent.model_egress import (
    ExecutionZone,
    ModelExecutionAuthorizer,
)
from industrial_ai_agent.agent.model_selection import (
    AGENT_CONSUMER,
    CURRENT_MODEL_CONSUMERS,
    CostClass,
    ModelCapability,
    ModelDefinition,
    QualityClass,
)
from industrial_ai_agent.application.document_content import AuthorizedDocumentContent
from industrial_ai_agent.application.model_configuration import (
    ModelConfigurationService,
)
from industrial_ai_agent.domain.security import DataClassification, SecurityContext
from industrial_ai_agent.infrastructure.api.app import create_app
from industrial_ai_agent.infrastructure.api.demo_security import (
    BearerTokenSecurityContextResolver,
)
from industrial_ai_agent.infrastructure.api.demo_sessions import DemoSessions
from industrial_ai_agent.infrastructure.api.run_store import InMemoryAgentRunStore

ROOT = Path(__file__).resolve().parents[2]
IMAGE = "nginx:1.29-alpine"
TOKEN_VARIABLES = {
    "public": "MCP_INDUSTRIAL_AGENT_PUBLIC_TOKEN",
    "internal": "MCP_INDUSTRIAL_AGENT_INTERNAL_TOKEN",
    "confidential": "MCP_INDUSTRIAL_AGENT_TOKEN",
    "restricted": "MCP_INDUSTRIAL_AGENT_RESTRICTED_TOKEN",
    "model-admin": "AGENT_API_MODEL_ADMIN_TOKEN",
}


class Documents:
    def __init__(self) -> None:
        self.contexts: list[SecurityContext] = []

    def get_document(self, document_id: str, security_context: SecurityContext):
        self.contexts.append(security_context)
        classification = DataClassification[document_id.upper()]
        if security_context.clearance < classification:
            return None
        return AuthorizedDocumentContent(
            content=f"{classification.name} synthetic document".encode(),
            media_type="text/plain",
            filename="synthetic.txt",
        )


class NoModelCalls:
    async def run_with_policy(self, *args, **kwargs):
        raise AssertionError("Gateway security tests must never execute an agent")


class Catalog:
    def list_models(self):
        return (self.get_model("test_local"),)

    def get_model(self, model_id):
        assert model_id == "test_local"
        return ModelDefinition(
            model_id=ModelId(model_id),
            display_name="Synthetic local model",
            provider="test",
            provider_model="unused",
            execution_zone=ExecutionZone.LOCAL,
            max_data_classification=DataClassification.RESTRICTED,
            capabilities=frozenset(ModelCapability),
            quality_class=QualityClass.STANDARD,
            cost_class=CostClass.LOW,
        )


class Assignments:
    def __init__(self) -> None:
        self.values = {}

    def get(self, consumer_id, data_classification):
        return self.values.get((consumer_id, data_classification))

    def list(self):
        return tuple(self.values.values())

    def upsert(self, assignment):
        assignment = replace(assignment, updated_at=datetime(2026, 10, 13, tzinfo=UTC))
        self.values[(assignment.consumer_id, assignment.data_classification)] = (
            assignment
        )
        return assignment


@pytest.fixture(scope="module")
def gateway(tmp_path_factory):
    available = subprocess.run(
        ["docker", "image", "inspect", IMAGE], capture_output=True, check=False
    )
    if available.returncode:
        pytest.skip(
            "INFRASTRUCTURE_UNAVAILABLE: local nginx image / Docker engine required"
        )
    directory = ROOT / "evals/results" / f"gateway-session-{uuid4().hex}"
    directory.mkdir(parents=True)
    tokens = {
        variable: secrets.token_urlsafe(32) for variable in TOKEN_VARIABLES.values()
    }
    app = create_app(
        NoModelCalls(),
        run_store=InMemoryAgentRunStore(),
        security_context_resolver=BearerTokenSecurityContextResolver.from_environment(
            tokens
        ),
        demo_sessions=DemoSessions(),
        document_content_reader=Documents(),
        model_configuration_service=ModelConfigurationService(
            catalog=Catalog(),
            assignments=Assignments(),
            supported_consumers=(AGENT_CONSUMER,),
            consumer_definitions=CURRENT_MODEL_CONSUMERS,
            authorizer=ModelExecutionAuthorizer(),
        ),
    )
    listener = socket.socket()
    listener.bind(("0.0.0.0", 0))
    port = listener.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, log_level="critical", access_log=False))
    thread = threading.Thread(target=server.run, kwargs={"sockets": [listener]})
    thread.start()
    config = (ROOT / "frontend/nginx.conf").read_text(encoding="utf-8")
    config = config.replace(
        "http://agent-api:8000", f"http://host.docker.internal:{port}"
    )
    config_file = directory / "default.conf"
    config_file.write_text(config, encoding="utf-8")
    name = f"gateway-session-{uuid4().hex}"
    started = False
    try:
        created = subprocess.run(
            [
                "docker",
                "run",
                "--pull=never",
                "--detach",
                "--name",
                name,
                "--add-host",
                "host.docker.internal:host-gateway",
                "--publish",
                "127.0.0.1::80",
                "--mount",
                f"type=bind,source={config_file},target=/etc/nginx/conf.d/default.conf,readonly",
                "--mount",
                f"type=bind,source={ROOT / 'frontend/index.html'},target=/usr/share/nginx/html/index.html,readonly",
                IMAGE,
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if created.returncode:
            raise RuntimeError(f"Synthetic gateway creation failed: {created.stderr}")
        started = True
        published = subprocess.run(
            ["docker", "port", name, "80"], check=True, capture_output=True, text=True
        ).stdout.strip()
        with httpx.Client(
            base_url=f"http://{published}", headers={"X-Demo-Session": "1"}, timeout=5
        ) as browser:
            deadline = time.monotonic() + 10
            while True:
                try:
                    if (
                        browser.get("/health").status_code == 200
                        and browser.get("/api/v1/auth/config").status_code == 200
                    ):
                        break
                except httpx.HTTPError:
                    pass
                if time.monotonic() > deadline:
                    raise RuntimeError("Synthetic gateway did not become ready")
                time.sleep(0.05)
            yield browser
    finally:
        if started:
            subprocess.run(
                ["docker", "rm", "--force", name], check=True, capture_output=True
            )
        server.should_exit = True
        thread.join(timeout=10)
        listener.close()
        assert not thread.is_alive()


@pytest.mark.parametrize("username", tuple(DemoSessions().users))
def test_real_gateway_resolves_session_roles_and_all_clearance_boundaries(
    gateway, username
):
    user = DemoSessions().users[username]
    response = gateway.post("/api/v1/auth/switch", json={"username": username})
    assert response.status_code == 200
    assert response.json() == user.metadata()
    assert gateway.get("/api/v1/auth/me").json() == user.metadata()
    for classification in DataClassification:
        for suffix in ("", "/download"):
            response = gateway.get(
                f"/api/v1/documents/{classification.name.lower()}{suffix}"
            )
            assert response.status_code == (
                200 if user.clearance >= classification else 404
            )
    for route in ("models", "model-consumers", "model-assignments"):
        assert gateway.get(f"/api/v1/{route}").status_code == (
            200 if user.roles else 403
        )
    payload = {
        "consumer_id": "agent",
        "data_classification": "PUBLIC",
        "model_id": "test_local",
    }
    assert gateway.put("/api/v1/model-assignments", json=payload).status_code == (
        200 if user.roles else 403
    )


def test_gateway_has_no_basic_challenge_tokens_or_password_assets(gateway):
    gateway.post("/api/v1/auth/logout", json={})
    response = gateway.get("/")
    assert response.status_code == 200
    assert "www-authenticate" not in response.headers
    for resource in (
        "/frontend.htpasswd",
        "/auth/frontend.htpasswd",
        "/config/demo-users.toml",
        "/default.conf",
    ):
        assert gateway.get(resource).status_code == 404
    assert (
        gateway.get(
            "/api/v1/models", headers={"Authorization": "Bearer arbitrary"}
        ).status_code
        == 401
    )
    assert (
        gateway.post(
            "/api/v1/auth/login", json={"username": "demo-admin", "password": "wrong"}
        ).status_code
        == 401
    )
    assert (
        gateway.post(
            "/api/v1/auth/login",
            json={"username": "demo-admin", "password": "demo-admin"},
        ).status_code
        == 200
    )
    assert gateway.get("/api/v1/models").status_code == 200

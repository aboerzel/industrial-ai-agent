"""Real Nginx -> FastAPI authorization; isolated synthetic records, no model calls.

Requires the locally installed nginx:1.29-alpine Docker image. No production data,
MCP service, database, provider, or existing container is modified.
"""

import asyncio
import secrets
import socket
import subprocess
import threading
import time
from collections.abc import Iterator
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import httpx
import pytest
import uvicorn

from industrial_ai_agent.agent.agent_run import AgentRunResult, AgentRunStatus
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


@dataclass
class Gateway:
    direct: httpx.Client
    browser: httpx.Client
    tokens: dict[str, str]
    password: str
    run_ids: dict[str, UUID]
    documents: Documents
    container: str

    def headers(self, identity: str, *, gateway: bool) -> dict[str, str]:
        if gateway:
            return {
                "Authorization": httpx.BasicAuth(identity, self.password)._auth_header
            }
        return {"Authorization": f"Bearer {self.tokens[TOKEN_VARIABLES[identity]]}"}


def _docker(*args: str, **kwargs) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["docker", *args], capture_output=True, text=True, check=True, **kwargs
    )


@pytest.fixture(scope="module")
def gateway(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Gateway]:
    available = subprocess.run(
        ["docker", "image", "inspect", IMAGE], capture_output=True, check=False
    )
    if available.returncode:
        pytest.skip(
            "INFRASTRUCTURE_UNAVAILABLE: local nginx image / Docker engine required"
        )
    directory = tmp_path_factory.mktemp("gateway-auth")
    password = secrets.token_urlsafe(32)
    hashed = _docker(
        "run",
        "--rm",
        "-i",
        IMAGE,
        "mkpasswd",
        "-m",
        "sha512",
        "-P",
        "0",
        input=password,
    ).stdout.strip()
    password_file = directory / "frontend.htpasswd"
    password_file.write_text(
        "".join(f"{user}:{hashed}\n" for user in (*TOKEN_VARIABLES, "unmapped")),
        encoding="utf-8",
        newline="\n",
    )
    tokens = {
        variable: secrets.token_urlsafe(32) for variable in TOKEN_VARIABLES.values()
    }
    store = InMemoryAgentRunStore()
    documents = Documents()
    run_ids = {}

    async def seed() -> None:
        for classification in DataClassification:
            run_id = uuid4()
            run_ids[classification.name.lower()] = run_id
            await store.create(
                run_id,
                data_classification=classification,
                request_text="Synthetic investigation",
            )
            await store.complete(
                run_id,
                AgentRunResult(
                    status=AgentRunStatus.SUCCESS,
                    final_answer="Synthetic evidence.",
                    tool_call_count=0,
                ),
            )

    asyncio.run(seed())
    app = create_app(
        NoModelCalls(),
        run_store=store,
        security_context_resolver=BearerTokenSecurityContextResolver.from_environment(
            tokens
        ),
        document_content_reader=documents,
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
    thread = threading.Thread(
        target=server.run, kwargs={"sockets": [listener]}, daemon=True
    )
    thread.start()
    config = (ROOT / "frontend/nginx.conf").read_text(encoding="utf-8")
    for variable, token in tokens.items():
        config = config.replace("${" + variable + "}", token)
    config = config.replace(
        "http://agent-api:8000", f"http://host.docker.internal:{port}"
    )
    config_file = directory / "default.conf"
    config_file.write_text(config, encoding="utf-8")
    name = f"gateway-security-{uuid4().hex}"
    started = False
    try:
        _docker(
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
            f"type=bind,source={password_file},target=/etc/nginx/auth/frontend.htpasswd,readonly",
            "--mount",
            f"type=bind,source={ROOT / 'frontend/index.html'},target=/usr/share/nginx/html/index.html,readonly",
            "--mount",
            f"type=bind,source={ROOT / 'frontend/js'},target=/usr/share/nginx/html/js,readonly",
            "--mount",
            f"type=bind,source={ROOT / 'frontend/css'},target=/usr/share/nginx/html/css,readonly",
            IMAGE,
        )
        started = True
        gateway_port = _docker("port", name, "80/tcp").stdout.strip().rsplit(":", 1)[1]
        with (
            httpx.Client(
                base_url=f"http://127.0.0.1:{port}", trust_env=False
            ) as direct,
            httpx.Client(
                base_url=f"http://127.0.0.1:{gateway_port}", trust_env=False
            ) as browser,
        ):
            deadline = time.monotonic() + 15
            while time.monotonic() < deadline:
                try:
                    if (
                        browser.get("/health").status_code == 200
                        and direct.get("/health").status_code == 200
                    ):
                        break
                except httpx.TransportError:
                    pass
                time.sleep(0.05)
            else:
                pytest.fail("Isolated gateway/API did not become ready")
            yield Gateway(direct, browser, tokens, password, run_ids, documents, name)
    finally:
        if started:
            _docker("rm", "--force", name)
        server.should_exit = True
        thread.join(timeout=5)
        listener.close()


def _paths(gateway: Gateway, classification: str, requested: str) -> list[str]:
    run_id = gateway.run_ids[classification]
    query = f"?user_clearance={requested}"
    return [
        f"/api/v1/documents/{classification}{query}",
        f"/api/v1/documents/{classification}/download{query}",
        f"/api/v1/runs/{run_id}{query}",
        f"/api/v1/investigations/{run_id}{query}",
        f"/api/v1/investigations/{run_id}/pdf{query}",
    ]


@pytest.mark.parametrize("classification", ["public", "confidential", "restricted"])
def test_anonymous_and_invalid_password_denied_on_every_protected_resource(
    gateway: Gateway, classification: str
) -> None:
    paths = _paths(gateway, classification, classification.upper()) + [
        "/api/v1/models",
        "/api/v1/model-consumers",
        "/api/v1/model-assignments",
    ]
    for path in paths:
        assert gateway.direct.get(path).status_code == 403
        assert gateway.browser.get(path).status_code == 401
        assert (
            gateway.browser.get(path, auth=("restricted", "wrong-password")).status_code
            == 401
        )
        assert (
            gateway.browser.get(
                path,
                headers={
                    "Authorization": f"Bearer {gateway.tokens[TOKEN_VARIABLES['restricted']]}"
                },
            ).status_code
            == 401
        )


@pytest.mark.parametrize(
    "identity,resource,requested,expected",
    [
        ("public", "public", "PUBLIC", 200),
        ("internal", "internal", "INTERNAL", 200),
        ("confidential", "confidential", "CONFIDENTIAL", 200),
        ("restricted", "restricted", "RESTRICTED", 200),
        ("confidential", "public", "PUBLIC", 200),
        ("confidential", "confidential", "PUBLIC", 404),
        ("public", "restricted", "PUBLIC", 404),
        ("public", "restricted", "RESTRICTED", 403),
        ("model-admin", "restricted", "RESTRICTED", 403),
    ],
)
def test_gateway_and_direct_api_enforce_identical_resource_authority(
    gateway: Gateway, identity: str, resource: str, requested: str, expected: int
) -> None:
    for path in _paths(gateway, resource, requested):
        direct = gateway.direct.get(
            path, headers=gateway.headers(identity, gateway=False)
        )
        browser = gateway.browser.get(
            path, headers=gateway.headers(identity, gateway=True)
        )
        assert direct.status_code == browser.status_code == expected, path
        if "/pdf" not in path:
            assert direct.content == browser.content
        else:
            assert direct.headers["content-type"] == browser.headers["content-type"]
    if identity == "confidential" and requested == "PUBLIC":
        assert gateway.documents.contexts[-1].clearance is DataClassification.PUBLIC
        assert gateway.documents.contexts[-1].subject_id == "local-api-confidential"


@pytest.mark.parametrize("identity", list(TOKEN_VARIABLES))
def test_model_admin_is_separate_for_reads_and_mutations(
    gateway: Gateway, identity: str
) -> None:
    for use_gateway, client in ((False, gateway.direct), (True, gateway.browser)):
        headers = gateway.headers(identity, gateway=use_gateway)
        expected = 200 if identity == "model-admin" else 403
        for path in (
            "/api/v1/models",
            "/api/v1/model-consumers",
            "/api/v1/model-assignments",
        ):
            assert client.get(path, headers=headers).status_code == expected
        response = client.put(
            "/api/v1/model-assignments",
            headers=headers,
            json={
                "consumer_id": "agent",
                "data_classification": "PUBLIC",
                "model_id": "test_local",
                "selection_mode": "MANUAL",
            },
        )
        assert response.status_code == expected


def test_forged_identity_headers_and_unmapped_users_never_grant_authority(
    gateway: Gateway,
) -> None:
    path = _paths(gateway, "restricted", "RESTRICTED")[0]
    forged = {
        "X-User": "model-admin",
        "X-Remote-User": "restricted",
        "X-Clearance": "RESTRICTED",
        "X-Permissions": "model-admin",
        "X-Client": "industrial-agent",
    }
    assert gateway.browser.get(path, headers=forged).status_code == 401
    assert (
        gateway.browser.get(
            path, auth=("public", gateway.password), headers=forged
        ).status_code
        == 403
    )
    assert (
        gateway.browser.get(path, auth=("unmapped", gateway.password)).status_code
        == 403
    )


def test_no_credentials_in_assets_config_errors_or_logs(gateway: Gateway) -> None:
    responses = [
        gateway.browser.get(path, auth=("model-admin", gateway.password))
        for path in (
            "/",
            "/index.html",
            "/js/api.js",
            "/js/app.js",
            "/nginx.conf",
            "/package.json",
            "/.env",
            "/frontend.htpasswd",
            "/auth/frontend.htpasswd",
            "/api/v1/documents/restricted?user_clearance=RESTRICTED",
        )
    ]
    for response in responses:
        for secret in (*gateway.tokens.values(), gateway.password):
            assert secret not in response.text
            assert secret not in str(response.headers)
    for response in responses[4:-1]:
        assert response.status_code == 404
    assert responses[-1].status_code == 403
    # Exercise hostile username logging, too; error log deliberately excludes it.
    assert gateway.browser.get("/", auth=(gateway.password, "wrong")).status_code == 401
    logs = _docker("logs", gateway.container)
    for secret in (*gateway.tokens.values(), gateway.password):
        assert secret not in logs.stdout + logs.stderr

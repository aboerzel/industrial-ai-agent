"""Isolated, labelled infrastructure owned exclusively by the release harness."""

from __future__ import annotations

import os
import secrets
import socket
import subprocess
import sys
import time
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

import psycopg
from alembic import command
from alembic.config import Config

ROOT = Path(__file__).resolve().parents[1]


def docker(*args: str, env=None) -> str:
    result = subprocess.run(
        ["docker", *args],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=env,
    )
    if result.returncode:
        # Never include credentials, full inspect output, or environment in errors.
        raise RuntimeError(f"Docker {args[0]} failed with exit {result.returncode}")
    return result.stdout


@contextmanager
def disposable_database():
    """Never accept a caller's database: create our own loopback disposable instance."""
    name = "verification-release-" + uuid4().hex[:12]
    database = "verification_release"
    password = secrets.token_hex(24)
    env = {
        **os.environ,
        "POSTGRES_USER": "postgres",
        "POSTGRES_DB": database,
        "POSTGRES_PASSWORD": password,
        "POSTGRES_APP_USER": "factory_app",
        "POSTGRES_APP_PASSWORD": password,
    }
    created = False
    try:
        docker(
            "run",
            "-d",
            "--name",
            name,
            "--label",
            "industrial.release-test=true",
            "--tmpfs",
            "/var/lib/postgresql",
            "-p",
            "127.0.0.1::5432",
            "--mount",
            f"type=bind,source={ROOT / 'database/init'},target=/docker-entrypoint-initdb.d,readonly",
            *[
                part
                for key in (
                    "POSTGRES_USER",
                    "POSTGRES_DB",
                    "POSTGRES_PASSWORD",
                    "POSTGRES_APP_USER",
                    "POSTGRES_APP_PASSWORD",
                )
                for part in ("-e", key)
            ],
            "postgres:18.6-alpine",
            env=env,
        )
        created = True
        port = docker("port", name, "5432/tcp").strip().rsplit(":", 1)[1]
        admin = f"postgresql+psycopg://postgres:{password}@127.0.0.1:{port}/{database}"
        app = f"postgresql+psycopg://factory_app:{password}@127.0.0.1:{port}/{database}"
        deadline = time.monotonic() + 90
        while True:
            try:
                with psycopg.connect(admin.replace("+psycopg", "")):
                    break
            except psycopg.OperationalError:
                if time.monotonic() >= deadline:
                    raise RuntimeError(
                        "Disposable PostgreSQL did not become ready"
                    ) from None
                time.sleep(0.25)
        selected = {
            "FACTORY_DATABASE_ADMIN_URL": admin,
            "FACTORY_DATABASE_URL": app,
            "AGENT_RUNTIME_DATABASE_URL": app,
            "POSTGRES_APP_USER": "factory_app",
            "FACTORY_DATA_ROOT": str(ROOT / "demo_factory"),
        }
        old = {key: os.environ.get(key) for key in selected}
        os.environ.update(selected)
        try:
            command.upgrade(Config(str(ROOT / "alembic.ini")), "head")
            from industrial_ai_agent.infrastructure.persistence.demo_seed import (
                seed_demo_data,
            )

            seed_demo_data(admin)
            with psycopg.connect(app.replace("+psycopg", "")) as connection:
                assert connection.execute(
                    "SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname=current_user"
                ).fetchone() == (False, False)
            yield {**os.environ, **selected}, name
        finally:
            for key, value in old.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value
    finally:
        if created:
            import json

            owner = json.loads(docker("inspect", name))[0]
            assert owner["Config"]["Labels"].get("industrial.release-test") == "true"
            docker("rm", "-f", name)


def python_command(*args: str) -> list[str]:
    return [sys.executable, *args]


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@contextmanager
def software_browser_environment(evidence: Path):
    """Run the unchanged application behind actual HTTP/MCP/RLS boundaries."""
    import httpx

    with disposable_database() as (base, _):
        factory_port, knowledge_port, hardware_port, api_port = [
            free_port() for _ in range(4)
        ]
        tokens = {
            key: secrets.token_urlsafe(32)
            for key in (
                "MCP_INDUSTRIAL_AGENT_PUBLIC_TOKEN",
                "MCP_INDUSTRIAL_AGENT_INTERNAL_TOKEN",
                "MCP_INDUSTRIAL_AGENT_TOKEN",
                "MCP_INDUSTRIAL_AGENT_RESTRICTED_TOKEN",
                "MCP_CODEX_DEVELOPMENT_TOKEN",
                "AGENT_API_MODEL_ADMIN_TOKEN",
            )
        }
        env = {
            **base,
            **tokens,
            "DEMO_AUTH_MODE": "true",
            "OTEL_ENABLED": "false",
            "LANGFUSE_ENABLED": "false",
            "AGENT_MCP_TRANSPORT": "http",
            "DOCUMENT_ROOT": str(ROOT / "demo_factory"),
            "FACTORY_MCP_URL": f"http://127.0.0.1:{factory_port}/mcp",
            "KNOWLEDGE_MCP_URL": f"http://127.0.0.1:{knowledge_port}/mcp",
            "HARDWARE_MCP_URL": f"http://127.0.0.1:{hardware_port}/mcp",
            "E2E_API_URL": f"http://127.0.0.1:{api_port}",
            "E2E_FRONTEND_URL": f"http://127.0.0.1:{api_port}",
            "E2E_EXECUTION_MODE": "SOFTWARE_DETERMINISTIC",
            "RELEASE_SOFTWARE_TOKEN": secrets.token_urlsafe(32),
        }
        processes, logs = [], []
        try:
            for name, args in (
                (
                    "factory",
                    [
                        "-m",
                        "industrial_ai_agent.infrastructure.factory_mcp_server",
                        "--transport",
                        "streamable-http",
                        "--port",
                        str(factory_port),
                    ],
                ),
                (
                    "knowledge",
                    [
                        str(ROOT / "tests/e2e/software-knowledge-server.py"),
                        str(knowledge_port),
                    ],
                ),
                (
                    "hardware",
                    [
                        "-m",
                        "industrial_ai_agent.infrastructure.hardware_mcp_server",
                        "--transport",
                        "streamable-http",
                        "--port",
                        str(hardware_port),
                    ],
                ),
                ("api", [str(ROOT / "tests/e2e/software-server.py"), str(api_port)]),
            ):
                log = (evidence / f"software-{name}.log").open("x", encoding="utf-8")
                logs.append(log)
                processes.append(
                    subprocess.Popen(
                        python_command(*args),
                        cwd=ROOT,
                        env=env,
                        stdout=log,
                        stderr=subprocess.STDOUT,
                    )
                )
            deadline = time.monotonic() + 120
            with httpx.Client(trust_env=False, timeout=5) as client:
                while True:
                    if any(p.poll() is not None for p in processes):
                        raise RuntimeError(
                            "Software fixture process exited; see first startup logs"
                        )
                    try:
                        if client.get(env["E2E_API_URL"] + "/ready").status_code == 200:
                            break
                    except httpx.HTTPError:
                        pass
                    if time.monotonic() >= deadline:
                        raise RuntimeError(
                            "Software fixture failed actual MCP-aware readiness"
                        )
                    time.sleep(0.25)
            yield env
        finally:
            for process in reversed(processes):
                if process.poll() is None:
                    process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=10)
            for log in logs:
                log.close()


@contextmanager
def knowledge_deployment_environment(evidence: Path):
    """Production image/pipeline, offline cache, disposable DB and embedding wire fake."""
    import json

    with disposable_database() as (base, database_name):
        suffix = uuid4().hex[:10]
        network, embedding, knowledge = [
            f"verification-{kind}-{suffix}"
            for kind in ("network", "embedding", "knowledge")
        ]
        image = docker("compose", "images", "-q", "knowledge-mcp").strip()
        image_id = json.loads(docker("image", "inspect", image))[0]["Id"]
        deployed = docker("compose", "ps", "-q", "knowledge-mcp").strip()
        mounts = json.loads(docker("inspect", deployed))[0]["Mounts"]
        cache = next(
            m["Name"]
            for m in mounts
            if m["Destination"] == "/home/app/.cache/huggingface"
        )
        created_network, children = False, []
        env_file = evidence / "kdep-private.env"
        try:
            docker(
                "network",
                "create",
                "--internal",
                "--label",
                "industrial.release-test=true",
                network,
            )
            created_network = True
            docker("network", "connect", "--alias", "postgres", network, database_name)
            docker(
                "run",
                "-d",
                "--name",
                embedding,
                "--network",
                network,
                "--network-alias",
                "ollama",
                "--label",
                "industrial.release-test=true",
                "--entrypoint",
                "python",
                "--no-healthcheck",
                "--mount",
                f"type=bind,source={ROOT / 'tests/fixtures/release-embedding-server.py'},target=/embedding.py,readonly",
                image_id,
                "/embedding.py",
            )
            children.append(embedding)
            embedding_address = json.loads(docker("inspect", embedding))[0][
                "NetworkSettings"
            ]["Networks"][network]["IPAddress"]
            from sqlalchemy.engine import make_url

            internal = (
                make_url(base["FACTORY_DATABASE_URL"])
                .set(host="postgres", port=5432)
                .render_as_string(hide_password=False)
            )
            variables = {
                "KNOWLEDGE_DATABASE_URL": internal,
                "KNOWLEDGE_MCP_OLLAMA_BASE_URL": "http://host.docker.internal:11434",
                "KNOWLEDGE_MCP_RERANKER_DEVICE": "cpu",
                "KNOWLEDGE_MCP_RERANKER_LOCAL_FILES_ONLY": "true",
                "HF_HUB_OFFLINE": "1",
                "TRANSFORMERS_OFFLINE": "1",
                "OTEL_ENABLED": "false",
                "DOCUMENT_ROOT": "/app/data/document-content",
                "KNOWLEDGE_ROOT": "/app/data/knowledge",
                **{
                    key: secrets.token_urlsafe(32)
                    for key in (
                        "MCP_INDUSTRIAL_AGENT_PUBLIC_TOKEN",
                        "MCP_INDUSTRIAL_AGENT_INTERNAL_TOKEN",
                        "MCP_INDUSTRIAL_AGENT_TOKEN",
                        "MCP_INDUSTRIAL_AGENT_RESTRICTED_TOKEN",
                        "MCP_CODEX_DEVELOPMENT_TOKEN",
                    )
                },
            }
            env_file.write_text(
                "\n".join(f"{k}={v}" for k, v in variables.items()), encoding="utf-8"
            )
            docker(
                "create",
                "--name",
                knowledge,
                "--network",
                network,
                "--add-host",
                f"host.docker.internal:{embedding_address}",
                "--label",
                "industrial.release-test=true",
                "--label",
                "industrial.knowledge-test=true",
                "--env-file",
                str(env_file),
                "--mount",
                f"type=volume,source={cache},target=/home/app/.cache/huggingface,readonly",
                "--mount",
                f"type=bind,source={ROOT / 'demo_factory'},target=/app/data/document-content,readonly",
                "--mount",
                f"type=bind,source={ROOT / 'knowledge_base'},target=/app/data/knowledge,readonly",
                image_id,
            )
            children.append(knowledge)
            docker("start", knowledge)
            wait_container_health(knowledge)
            yield (
                {
                    **base,
                    "KNOWLEDGE_TEST_IMAGE_ID": image_id,
                    "KNOWLEDGE_TEST_CONTAINER": knowledge,
                },
                knowledge,
            )
        finally:
            env_file.unlink(missing_ok=True)
            for name in reversed(children):
                details = json.loads(docker("inspect", name))[0]
                assert (
                    details["Config"]["Labels"].get("industrial.release-test") == "true"
                )
                log = subprocess.run(
                    ["docker", "logs", name],
                    check=False,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                )
                (evidence / f"{name}.log").write_text(
                    log.stdout + "\n" + log.stderr, encoding="utf-8"
                )
                docker("rm", "-f", name)
            if created_network:
                docker("network", "disconnect", network, database_name)
                docker("network", "rm", network)


def wait_container_health(name: str):
    import json

    deadline = time.monotonic() + 420
    while True:
        state = json.loads(docker("inspect", name))[0]["State"]
        if state.get("Health", {}).get("Status") == "healthy":
            return
        if not state["Running"] or time.monotonic() >= deadline:
            raise RuntimeError(
                "Isolated KDEP container failed actual readiness; first logs retained"
            )
        time.sleep(1)

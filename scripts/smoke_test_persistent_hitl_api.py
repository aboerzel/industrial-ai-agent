"""Run the local FastAPI -> MCP -> PostgreSQL HITL restart smoke path."""

import argparse
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx
from sqlalchemy import func, select

from industrial_ai_agent.domain.security import DEMO_ENGINEER_SECURITY_CONTEXT
from industrial_ai_agent.infrastructure.local_environment import load_local_environment
from industrial_ai_agent.infrastructure.persistence.models import (
    MaintenanceTicketRecord,
)
from industrial_ai_agent.infrastructure.persistence.postgres import (
    PostgreSqlSessionFactory,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PROMPT = (
    "Perform this exact evidence sequence before any maintenance-ticket proposal: "
    "(1) call get_product_history for P4711, (2) call get_machine_status for S04, "
    "and (3) call search_documentation for QUALITY-09 at S04. Do not propose or create "
    "a ticket until all three read-only calls have completed. Then propose a maintenance "
    "ticket for S04 with summary 'Investigate recurring QUALITY-09 at S04'."
)
EXPECTED_READ_TOOLS = (
    "get_product_history",
    "get_machine_status",
    "search_documentation",
)
EXPECTED_ALL_TOOLS = (*EXPECTED_READ_TOOLS, "create_maintenance_ticket")


def main() -> None:
    decision = _parse_args().decision
    load_local_environment(PROJECT_ROOT / ".env")
    database_url = os.getenv("AGENT_RUNTIME_DATABASE_URL") or os.getenv(
        "FACTORY_DATABASE_URL"
    )
    if not database_url:
        raise RuntimeError(
            "AGENT_RUNTIME_DATABASE_URL or FACTORY_DATABASE_URL is required"
        )

    ticket_count_before = _ticket_count(database_url)
    port = _find_available_port()
    environment = dict(os.environ)
    environment.update(
        {
            "AGENT_API_HOST": "127.0.0.1",
            "AGENT_API_PORT": str(port),
            "AGENT_MCP_TRANSPORT": "http",
            "AGENT_RUNTIME_DATABASE_URL": database_url,
        }
    )
    base_url = f"http://127.0.0.1:{port}"

    first_process = _start_api(environment)
    try:
        _wait_for_health(first_process, base_url)
        with httpx.Client(timeout=300.0) as client:
            started = client.post(f"{base_url}/api/v1/runs", json={"message": PROMPT})
            started.raise_for_status()
            waiting = started.json()
        _assert_waiting_for_approval(waiting)
        run_id = waiting["run_id"]
        if _ticket_count(database_url) != ticket_count_before:
            raise RuntimeError("Ticket was created before approval")
    finally:
        _stop(first_process)

    second_process = _start_api(environment)
    try:
        _wait_for_health(second_process, base_url)
        with httpx.Client(timeout=300.0) as client:
            restored = client.get(f"{base_url}/api/v1/runs/{run_id}")
            restored.raise_for_status()
            _assert_waiting_for_approval(restored.json())
            approved = client.post(
                f"{base_url}/api/v1/runs/{run_id}/resume",
                json={"decision": decision},
            )
            approved.raise_for_status()
            successful = approved.json()
            if decision == "approve":
                duplicate = client.post(
                    f"{base_url}/api/v1/runs/{run_id}/resume",
                    json={"decision": "approve"},
                )
        _assert_success(
            successful,
            EXPECTED_ALL_TOOLS if decision == "approve" else EXPECTED_READ_TOOLS,
        )
        ticket_count_after = _ticket_count(database_url)
        if decision == "approve":
            if duplicate.status_code != 409:
                raise RuntimeError("Duplicate approval was not rejected")
            if ticket_count_after != ticket_count_before + 1:
                raise RuntimeError(
                    "Approval did not create exactly one maintenance ticket"
                )
        elif ticket_count_after != ticket_count_before:
            raise RuntimeError("Rejection created a maintenance ticket")
    finally:
        _stop(second_process)

    print("SUCCESS")
    print(f"run_id={run_id}")
    print("status=success")
    expected_tools = (
        EXPECTED_ALL_TOOLS if decision == "approve" else EXPECTED_READ_TOOLS
    )
    print(f"decision={decision}")
    print(f"tool_calls={','.join(expected_tools)}")
    print(f"ticket_count_delta={1 if decision == 'approve' else 0}")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--decision", choices=("approve", "reject"), default="approve")
    return parser.parse_args()


def _start_api(environment: dict[str, str]) -> subprocess.Popen[bytes]:
    return subprocess.Popen(
        [sys.executable, "-m", "industrial_ai_agent.infrastructure.agent_api"],
        cwd=PROJECT_ROOT,
        env=environment,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def _stop(process: subprocess.Popen[bytes]) -> None:
    process.terminate()
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=10)


def _find_available_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def _wait_for_health(process: subprocess.Popen[bytes], base_url: str) -> None:
    deadline = time.monotonic() + 30
    with httpx.Client(timeout=1.0) as client:
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise RuntimeError("FastAPI smoke process exited during startup")
            try:
                response = client.get(f"{base_url}/health")
            except httpx.HTTPError:
                time.sleep(0.1)
                continue
            if response.status_code == 200 and response.json() == {"status": "ok"}:
                return
            time.sleep(0.1)
    raise RuntimeError("FastAPI smoke process did not become healthy within 30 seconds")


def _assert_waiting_for_approval(payload: object) -> None:
    if not isinstance(payload, dict):
        raise TypeError("FastAPI smoke did not return a JSON object")
    if payload.get("status") != "waiting_for_approval":
        raise RuntimeError("FastAPI smoke did not pause for approval")
    approval = payload.get("approval_request")
    if not isinstance(approval, dict):
        raise TypeError("FastAPI smoke did not return an approval request")
    if approval.get("action") != "create_maintenance_ticket":
        raise RuntimeError("FastAPI smoke paused for an unexpected action")
    if approval.get("model_profile") != "local_quality":
        raise RuntimeError("FastAPI smoke did not route to local_quality")
    tool_names = _tool_names(payload)
    if tool_names != EXPECTED_READ_TOOLS:
        raise RuntimeError(
            f"FastAPI smoke expected {EXPECTED_READ_TOOLS}, got {tool_names}"
        )


def _assert_success(payload: object, expected_tools: tuple[str, ...]) -> None:
    if not isinstance(payload, dict):
        raise TypeError("FastAPI smoke did not return a JSON object")
    if payload.get("status") != "success":
        raise RuntimeError("FastAPI smoke did not return success")
    tool_names = _tool_names(payload)
    if tool_names != expected_tools:
        raise RuntimeError(f"FastAPI smoke expected {expected_tools}, got {tool_names}")


def _tool_names(payload: dict[str, object]) -> tuple[str, ...]:
    calls = payload.get("tool_calls")
    if not isinstance(calls, list):
        raise TypeError("FastAPI smoke did not return tool calls")
    return tuple(
        call["tool"]
        for call in calls
        if isinstance(call, dict) and isinstance(call.get("tool"), str)
    )


def _ticket_count(database_url: str) -> int:
    sessions = PostgreSqlSessionFactory(database_url)
    try:
        with sessions.session(DEMO_ENGINEER_SECURITY_CONTEXT) as session:
            return int(
                session.scalar(
                    select(func.count()).select_from(MaintenanceTicketRecord)
                )
                or 0
            )
    finally:
        sessions.dispose()


if __name__ == "__main__":
    main()

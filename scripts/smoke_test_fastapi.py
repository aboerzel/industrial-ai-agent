"""Run the local FastAPI-to-LangGraph-to-Multi-MCP confidential smoke path."""

import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PROMPT = (
    "P4711 failed during production. Investigate what happened and check the current "
    "status of the relevant station. Then consult the local technical documentation "
    "for the relevant fault and provide a final diagnosis."
)
EXPECTED_TOOLS = [
    "get_product_history",
    "get_machine_status",
    "search_documentation",
]


def main() -> None:
    port = _find_available_port()
    environment = dict(os.environ)
    environment["AGENT_API_HOST"] = "127.0.0.1"
    environment["AGENT_API_PORT"] = str(port)
    environment["AGENT_MCP_TRANSPORT"] = "http"

    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "industrial_ai_agent.infrastructure.agent_api",
        ],
        cwd=PROJECT_ROOT,
        env=environment,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    base_url = f"http://127.0.0.1:{port}"
    try:
        _wait_for_health(process, base_url)
        with httpx.Client(timeout=300.0) as client:
            response = client.post(f"{base_url}/api/v1/runs", json={"message": PROMPT})
            response.raise_for_status()
            payload = response.json()
            _assert_success_payload(payload)

            stored = client.get(f"{base_url}/api/v1/runs/{payload['run_id']}")
            stored.raise_for_status()
            if stored.json() != payload:
                raise RuntimeError("Stored API run does not match its POST response")
    finally:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=10)

    print("SUCCESS")
    print(f"run_id={payload['run_id']}")
    print(f"status={payload['status']}")
    print(f"tool_calls={','.join(call['tool'] for call in payload['tool_calls'])}")


def _find_available_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def _wait_for_health(process: subprocess.Popen[bytes], base_url: str) -> None:
    deadline = time.monotonic() + 15
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
    raise RuntimeError("FastAPI smoke process did not become healthy within 15 seconds")


def _assert_success_payload(payload: object) -> None:
    if not isinstance(payload, dict):
        raise TypeError("FastAPI smoke did not return a JSON object")
    if payload.get("status") != "success":
        raise RuntimeError("FastAPI smoke did not return success")
    if not isinstance(payload.get("run_id"), str) or not payload["run_id"]:
        raise RuntimeError("FastAPI smoke did not return a run_id")
    if not isinstance(payload.get("answer"), str) or not payload["answer"].strip():
        raise RuntimeError("FastAPI smoke did not return an answer")
    tool_calls = payload.get("tool_calls")
    if not isinstance(tool_calls, list):
        raise TypeError("FastAPI smoke did not return tool calls")
    actual_tools = [call.get("tool") for call in tool_calls if isinstance(call, dict)]
    if actual_tools != EXPECTED_TOOLS:
        raise RuntimeError(
            f"FastAPI smoke expected {EXPECTED_TOOLS}, got {actual_tools}"
        )


if __name__ == "__main__":
    main()

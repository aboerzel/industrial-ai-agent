"""Shared local MCP service fixtures for explicit integration tests."""

import socket
import subprocess
import sys
import time
from collections.abc import Iterator

import pytest

from industrial_ai_agent.infrastructure.factory_mcp_client import (
    StreamableHttpServerParameters,
)

_IN_MEMORY_FACTORY_HTTP_SERVER = """
import os
import sys
from industrial_ai_agent.infrastructure.factory_mcp_server import create_default_factory_mcp_server

os.environ.pop('FACTORY_DATABASE_URL', None)
create_default_factory_mcp_server().run(
    transport='streamable-http',
    host='127.0.0.1',
    port=int(sys.argv[1]),
    streamable_http_path='/mcp',
)
"""


@pytest.fixture(scope="module")
def factory_mcp_http_transport() -> Iterator[StreamableHttpServerParameters]:
    """Run one SDK Streamable HTTP server for an integration-test module."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]

    process = subprocess.Popen(
        [sys.executable, "-c", _IN_MEMORY_FACTORY_HTTP_SERVER, str(port)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        _wait_for_listening_port(process, port)
        yield StreamableHttpServerParameters(url=f"http://127.0.0.1:{port}/mcp")
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


def _wait_for_listening_port(process: subprocess.Popen[bytes], port: int) -> None:
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError("Factory MCP HTTP test server exited during startup")
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as client:
            if client.connect_ex(("127.0.0.1", port)) == 0:
                return
        time.sleep(0.05)
    raise RuntimeError("Factory MCP HTTP test server did not start within 5 seconds")

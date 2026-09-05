import asyncio
import inspect
import socket
import subprocess
import sys
import time
from collections.abc import Iterator

import pytest
from mcp.client.stdio import StdioServerParameters
from mcp.types import CallToolResult

from industrial_ai_agent.infrastructure.factory_mcp_client import (
    StreamableHttpServerParameters,
    open_mcp_session,
)
from industrial_ai_agent.infrastructure.knowledge_mcp_server import (
    KNOWLEDGE_MCP_SERVER_NAME,
    KNOWLEDGE_MCP_SERVER_VERSION,
    create_knowledge_mcp_server,
)
from industrial_ai_agent.tools.documentation_search import (
    DocumentationSearchResult,
)

_TEST_SERVER_SOURCE = """
import sys
from industrial_ai_agent.domain.knowledge_retrieval import KnowledgeRetrievalResult
from industrial_ai_agent.tools.documentation_search import DocumentationSearchCapability
from industrial_ai_agent.infrastructure.knowledge_mcp_server import create_knowledge_mcp_server

class Retriever:
    def search(self, query, limit):
        return (KnowledgeRetrievalResult(
            content="Known E-STOP-17 procedure.",
            document_id="error_codes",
            source="error_codes.md",
            chunk_id="error_codes::chunk-002",
            relevance_score=0.9,
            metadata={"title": "E-STOP-17"},
        ),)[:limit]

server = create_knowledge_mcp_server(
    documentation_search=DocumentationSearchCapability(Retriever())
)
if sys.argv[1] == "stdio":
    server.run(transport="stdio")
else:
    server.run(transport="streamable-http", host="127.0.0.1", port=int(sys.argv[2]), streamable_http_path="/mcp")
"""


def test_knowledge_mcp_server_advertises_the_expected_schema() -> None:
    tools = asyncio.run(
        create_knowledge_mcp_server(
            documentation_search=_RecordingDocumentationSearchCapability(),  # type: ignore[arg-type]
        ).list_tools()
    )

    assert [tool.name for tool in tools] == ["search_documentation"]
    schema = tools[0].input_schema
    assert schema["required"] == ["query"]
    assert schema["properties"]["query"]["type"] == "string"
    assert schema["properties"]["top_k"]["type"] == "integer"
    assert schema["properties"]["top_k"]["default"] == 3
    assert schema["additionalProperties"] is False
    assert schema["properties"]["top_k"]["maximum"] == 5


def test_knowledge_mcp_handler_delegates_and_preserves_structured_provenance() -> None:
    capability = _RecordingDocumentationSearchCapability()
    server = create_knowledge_mcp_server(documentation_search=capability)  # type: ignore[arg-type]

    async def call_tool() -> dict[str, object]:
        response = await server.call_tool(
            "search_documentation", {"query": "S04 E-STOP-17", "top_k": 1}
        )
        assert isinstance(response, CallToolResult)
        assert response.structured_content is not None
        return dict(response.structured_content)  # type: ignore[arg-type]

    result = asyncio.run(call_tool())

    assert capability.requests == [("S04 E-STOP-17", 1)]
    assert result["query"] == "S04 E-STOP-17"
    assert result["results"] == [
        {
            "rank": 1,
            "content": "Known E-STOP-17 procedure.",
            "document_id": "error_codes",
            "source": "error_codes.md",
            "chunk_id": "error_codes::chunk-002",
            "relevance_score": 0.9,
            "classification": 0,
            "metadata": {"title": "E-STOP-17"},
        }
    ]


def test_knowledge_capability_result_does_not_depend_on_mcp_or_infrastructure() -> None:
    source = inspect.getsource(DocumentationSearchResult).casefold()
    assert "mcp" not in source
    assert "infrastructure" not in source


def test_knowledge_mcp_stdio_and_http_have_equivalent_discovery_and_results(
    knowledge_mcp_http_transport: StreamableHttpServerParameters,
) -> None:
    stdio_result = asyncio.run(
        _discover_and_search(
            StdioServerParameters(
                command=sys.executable,
                args=["-c", _TEST_SERVER_SOURCE, "stdio"],
            )
        )
    )
    http_result = asyncio.run(_discover_and_search(knowledge_mcp_http_transport))

    assert http_result == stdio_result
    assert http_result["server_name"] == KNOWLEDGE_MCP_SERVER_NAME
    assert http_result["server_version"] == KNOWLEDGE_MCP_SERVER_VERSION


@pytest.fixture(scope="module")
def knowledge_mcp_http_transport() -> Iterator[StreamableHttpServerParameters]:
    port = _free_port()
    process = subprocess.Popen(
        [sys.executable, "-c", _TEST_SERVER_SOURCE, "http", str(port)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
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


async def _discover_and_search(
    transport: StdioServerParameters | StreamableHttpServerParameters,
) -> dict[str, object]:
    async with open_mcp_session(transport) as session:
        initialized = await session.initialize()
        listed_tools = await session.list_tools()
        response = await session.call_tool(
            "search_documentation", {"query": " E-STOP-17 ", "top_k": 3}
        )
    assert response.structured_content is not None
    return {
        "server_name": initialized.server_info.name,
        "server_version": initialized.server_info.version,
        "tools": tuple(tool.name for tool in listed_tools.tools),
        "schemas": {tool.name: dict(tool.input_schema) for tool in listed_tools.tools},
        "result": response.structured_content,
    }


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        return listener.getsockname()[1]


def _wait_for_listening_port(process: subprocess.Popen[str], port: int) -> None:
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        if process.poll() is not None:
            stderr = process.stderr.read() if process.stderr is not None else ""
            raise RuntimeError(
                f"Knowledge MCP HTTP test server exited during startup: {stderr}"
            )
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as client:
            if client.connect_ex(("127.0.0.1", port)) == 0:
                return
        time.sleep(0.05)
    raise RuntimeError("Knowledge MCP HTTP test server did not start within 5 seconds")


class _RecordingDocumentationSearchCapability:
    def __init__(self) -> None:
        self.requests: list[tuple[str, int]] = []

    def search_documentation(
        self, query: str, top_k: int = 3
    ) -> DocumentationSearchResult:
        self.requests.append((query, top_k))
        return DocumentationSearchResult(
            query=query,
            results=(_result(),),
        )


def _result():
    from industrial_ai_agent.domain.knowledge_retrieval import KnowledgeRetrievalResult

    return KnowledgeRetrievalResult(
        content="Known E-STOP-17 procedure.",
        document_id="error_codes",
        source="error_codes.md",
        chunk_id="error_codes::chunk-002",
        relevance_score=0.9,
        metadata={"title": "E-STOP-17"},
    )

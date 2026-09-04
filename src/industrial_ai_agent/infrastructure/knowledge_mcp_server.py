"""MCP server adapter and deployment entry point for local knowledge retrieval."""

import argparse
import os
from pathlib import Path
from typing import Any

from mcp.server.mcpserver import MCPServer

from industrial_ai_agent.tools.documentation_search import DocumentationSearchCapability

KNOWLEDGE_MCP_SERVER_NAME = "knowledge_mcp"
KNOWLEDGE_MCP_SERVER_VERSION = "0.1.0"
KNOWLEDGE_MCP_HTTP_PATH = "/mcp"
PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_KNOWLEDGE_BASE_PATH = PROJECT_ROOT / "knowledge_base"


def create_knowledge_mcp_server(
    *,
    documentation_search: DocumentationSearchCapability,
) -> MCPServer:
    """Create an MCP adapter over the injected documentation-search capability."""
    server = MCPServer(
        name=KNOWLEDGE_MCP_SERVER_NAME,
        version=KNOWLEDGE_MCP_SERVER_VERSION,
        description="Read-only local technical documentation search.",
    )

    @server.tool(
        name="search_documentation",
        description="Search local technical documentation with preserved chunk provenance.",
        structured_output=True,
    )
    def search_documentation(query: str, top_k: int = 3) -> dict[str, Any]:
        result = documentation_search.search_documentation(query, top_k)
        return {
            "query": result.query,
            "results": [
                {"rank": rank, **item.model_dump(mode="json")}
                for rank, item in enumerate(result.results, start=1)
            ],
        }

    return server


def create_default_knowledge_mcp_server(
    *,
    knowledge_base_path: Path = DEFAULT_KNOWLEDGE_BASE_PATH,
    embedding_base_url: str | None = None,
    reranker_device: str | None = None,
) -> MCPServer:
    """Assemble the frozen local retrieval pipeline at the server composition root."""
    # Import expensive local-model adapters only when this production composition runs.
    from industrial_ai_agent.infrastructure.in_memory_lexical_knowledge_retriever import (
        load_markdown_chunks,
    )
    from industrial_ai_agent.infrastructure.knowledge_retrieval_composition import (
        create_reranked_knowledge_retriever,
    )

    retriever = create_reranked_knowledge_retriever(
        load_markdown_chunks(knowledge_base_path),
        embedding_base_url=embedding_base_url,
        reranker_device=reranker_device,
    )
    return create_knowledge_mcp_server(
        documentation_search=DocumentationSearchCapability(retriever)
    )


def main() -> None:
    """Run the knowledge server through the transport chosen at process startup."""
    args = _parse_args()
    server = create_default_knowledge_mcp_server(
        knowledge_base_path=args.knowledge_base,
        embedding_base_url=args.ollama_base_url,
        reranker_device=args.reranker_device,
    )
    if args.transport == "stdio":
        server.run(transport="stdio")
        return
    server.run(
        transport="streamable-http",
        host=args.host,
        port=args.port,
        streamable_http_path=KNOWLEDGE_MCP_HTTP_PATH,
    )


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the knowledge MCP server.")
    parser.add_argument(
        "--transport",
        choices=("stdio", "streamable-http"),
        default=os.getenv("KNOWLEDGE_MCP_TRANSPORT", "stdio"),
    )
    parser.add_argument(
        "--host",
        default=os.getenv("KNOWLEDGE_MCP_HOST", "127.0.0.1"),
    )
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.getenv("KNOWLEDGE_MCP_PORT", "8002")),
    )
    parser.add_argument(
        "--knowledge-base",
        type=Path,
        default=Path(
            os.getenv("KNOWLEDGE_MCP_KNOWLEDGE_BASE", DEFAULT_KNOWLEDGE_BASE_PATH)
        ),
    )
    parser.add_argument(
        "--ollama-base-url",
        default=os.getenv("KNOWLEDGE_MCP_OLLAMA_BASE_URL"),
    )
    parser.add_argument(
        "--reranker-device",
        default=os.getenv("KNOWLEDGE_MCP_RERANKER_DEVICE"),
    )
    return parser.parse_args()


if __name__ == "__main__":
    main()

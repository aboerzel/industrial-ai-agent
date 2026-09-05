"""MCP server adapter and deployment entry point for local knowledge retrieval."""

import argparse
import os
from collections.abc import Callable
from pathlib import Path
from threading import Lock
from time import perf_counter
from typing import Any

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.context import Context
from mcp.types import ToolAnnotations

from industrial_ai_agent.application.mcp_access import McpPermission
from industrial_ai_agent.domain.security import (
    DEMO_ENGINEER_SECURITY_CONTEXT,
    DataClassification,
    SecurityContext,
)
from industrial_ai_agent.infrastructure.mcp_access_control import (
    McpHttpAccessControl,
    create_demo_mcp_access_control,
    install_mcp_http_access_control,
)
from industrial_ai_agent.infrastructure.mcp_schema_validation import (
    require_strict_mcp_tool_arguments,
)
from industrial_ai_agent.infrastructure.telemetry import (
    Telemetry,
    TelemetryConfiguration,
    configure_telemetry,
    run_instrumented_mcp_http_server,
    sanitized_error_code,
)
from industrial_ai_agent.tools.documentation_search import DocumentationSearchCapability
from industrial_ai_agent.tools.tool_contracts import (
    DocumentationQuery,
    DocumentationResultLimit,
)

KNOWLEDGE_MCP_SERVER_NAME = "knowledge_mcp"
KNOWLEDGE_MCP_SERVER_VERSION = "0.1.0"
KNOWLEDGE_MCP_HTTP_PATH = "/mcp"
PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_KNOWLEDGE_BASE_PATH = PROJECT_ROOT / "knowledge_base"
DEFAULT_DEMO_FACTORY_ROOT = PROJECT_ROOT / "demo_factory"

_KNOWLEDGE_TOOL_PERMISSIONS = {"search_documentation": McpPermission.READ_KNOWLEDGE}
type DocumentationSearchForContext = Callable[
    [SecurityContext], DocumentationSearchCapability
]


def create_knowledge_mcp_server(
    *,
    documentation_search: DocumentationSearchCapability,
    access_control: McpHttpAccessControl | None = None,
    documentation_search_for_context: DocumentationSearchForContext | None = None,
    telemetry: Telemetry | None = None,
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
        annotations=ToolAnnotations(read_only_hint=True),
    )
    def search_documentation(
        query: DocumentationQuery,
        top_k: DocumentationResultLimit = 3,
        ctx: Context | None = None,
    ) -> dict[str, Any]:
        result = _invoke_knowledge_search(
            telemetry=telemetry,
            action=lambda: _documentation_search_for_request(
                ctx=ctx,
                tool_name="search_documentation",
                fallback=documentation_search,
                access_control=access_control,
                documentation_search_for_context=documentation_search_for_context,
            ).search_documentation(query, top_k),
        )
        return {
            "query": result.query,
            "results": [
                {"rank": rank, **item.model_dump(mode="json")}
                for rank, item in enumerate(result.results, start=1)
            ],
        }

    require_strict_mcp_tool_arguments(server, "search_documentation")
    if access_control is not None:
        install_mcp_http_access_control(server, access_control)

    return server


def create_default_knowledge_mcp_server(
    *,
    knowledge_base_path: Path = DEFAULT_KNOWLEDGE_BASE_PATH,
    embedding_base_url: str | None = None,
    reranker_device: str | None = None,
    reranker_local_files_only: bool = True,
    database_url: str | None = None,
    demo_factory_root: Path = DEFAULT_DEMO_FACTORY_ROOT,
    telemetry: Telemetry | None = None,
) -> MCPServer:
    """Assemble the frozen local retrieval pipeline at the server composition root."""
    # Import expensive local-model adapters only when this production composition runs.
    from industrial_ai_agent.infrastructure.knowledge_retrieval_composition import (
        create_reranked_knowledge_retriever,
    )

    if database_url:
        from industrial_ai_agent.infrastructure.docling_ingestion import (
            DoclingDocumentIngestor,
            eligible_catalog_documents,
        )
        from industrial_ai_agent.infrastructure.persistence.postgres import (
            PostgreSqlDocumentCatalogRepository,
            PostgreSqlSessionFactory,
        )

        catalog = PostgreSqlDocumentCatalogRepository(
            PostgreSqlSessionFactory(database_url), DEMO_ENGINEER_SECURITY_CONTEXT
        ).list_documents()
        eligible_catalog = eligible_catalog_documents(
            catalog, DEMO_ENGINEER_SECURITY_CONTEXT
        )
        ingestor = DoclingDocumentIngestor(demo_factory_root)
        chunks = tuple(
            chunk
            for document in eligible_catalog
            for chunk in ingestor.ingest(document)
        )
    else:
        from industrial_ai_agent.infrastructure.in_memory_lexical_knowledge_retriever import (
            load_markdown_chunks,
        )

        chunks = load_markdown_chunks(knowledge_base_path)
    retriever = create_reranked_knowledge_retriever(
        chunks,
        embedding_base_url=embedding_base_url,
        reranker_device=reranker_device,
        reranker_local_files_only=reranker_local_files_only,
        telemetry=telemetry,
    )
    return create_knowledge_mcp_server(
        documentation_search=DocumentationSearchCapability(retriever),
        telemetry=telemetry,
    )


class ClearanceAwareDocumentationSearchFactory:
    """Build isolated retrieval pipelines keyed by the full request security context."""

    def __init__(
        self,
        *,
        database_url: str,
        embedding_base_url: str | None,
        reranker_device: str | None,
        reranker_local_files_only: bool,
        demo_factory_root: Path,
        telemetry: Telemetry | None = None,
    ) -> None:
        self._database_url = database_url
        self._embedding_base_url = embedding_base_url
        self._reranker_device = reranker_device
        self._reranker_local_files_only = reranker_local_files_only
        self._demo_factory_root = demo_factory_root
        self._telemetry = telemetry
        self._cache: dict[SecurityContext, DocumentationSearchCapability] = {}
        self._lock = Lock()

    def for_context(
        self, security_context: SecurityContext
    ) -> DocumentationSearchCapability:
        with self._lock:
            cached = self._cache.get(security_context)
            if cached is not None:
                return cached
            capability = self._build(security_context)
            self._cache[security_context] = capability
            return capability

    def _build(
        self, security_context: SecurityContext
    ) -> DocumentationSearchCapability:
        from industrial_ai_agent.infrastructure.docling_ingestion import (
            DoclingDocumentIngestor,
            eligible_catalog_documents,
        )
        from industrial_ai_agent.infrastructure.knowledge_retrieval_composition import (
            create_reranked_knowledge_retriever,
        )
        from industrial_ai_agent.infrastructure.persistence.postgres import (
            PostgreSqlDocumentCatalogRepository,
            PostgreSqlSessionFactory,
        )

        catalog = PostgreSqlDocumentCatalogRepository(
            PostgreSqlSessionFactory(self._database_url), security_context
        ).list_documents()
        eligible_catalog = eligible_catalog_documents(catalog, security_context)
        ingestor = DoclingDocumentIngestor(self._demo_factory_root)
        chunks = tuple(
            chunk
            for document in eligible_catalog
            for chunk in ingestor.ingest(document)
        )
        retriever = create_reranked_knowledge_retriever(
            chunks,
            embedding_base_url=self._embedding_base_url,
            reranker_device=self._reranker_device,
            reranker_local_files_only=self._reranker_local_files_only,
            telemetry=self._telemetry,
        )
        return DocumentationSearchCapability(retriever)


def create_secure_knowledge_mcp_server(
    *,
    embedding_base_url: str | None,
    reranker_device: str | None,
    reranker_local_files_only: bool,
    database_url: str,
    demo_factory_root: Path,
    telemetry: Telemetry | None = None,
) -> MCPServer:
    """Build the HTTP composition with clearance-isolated retrieval pipelines."""
    search_factory = ClearanceAwareDocumentationSearchFactory(
        database_url=database_url,
        embedding_base_url=embedding_base_url,
        reranker_device=reranker_device,
        reranker_local_files_only=reranker_local_files_only,
        demo_factory_root=demo_factory_root,
        telemetry=telemetry,
    )
    # This fallback is never reached by authenticated HTTP calls. It remains PUBLIC
    # so constructing the secure server never parses a higher-clearance corpus.
    fallback = search_factory.for_context(
        SecurityContext(
            subject_id="secure-http-fallback",
            roles=("fallback",),
            clearance=DataClassification.PUBLIC,
            authenticated=False,
        )
    )
    server: MCPServer

    async def listed_tools():
        return await server.list_tools()

    access_control = create_demo_mcp_access_control(
        tools=listed_tools,
        required_permission=_required_knowledge_permission,
    )
    server = create_knowledge_mcp_server(
        documentation_search=fallback,
        access_control=access_control,
        documentation_search_for_context=search_factory.for_context,
        telemetry=telemetry,
    )
    return server


def main() -> None:
    """Run the knowledge server through the transport chosen at process startup."""
    args = _parse_args()
    telemetry = _create_knowledge_telemetry() if args.transport != "stdio" else None
    database_url = os.getenv("KNOWLEDGE_DATABASE_URL")
    demo_factory_root = Path(
        os.getenv("KNOWLEDGE_MCP_DEMO_FACTORY_ROOT", DEFAULT_DEMO_FACTORY_ROOT)
    )
    server = (
        create_default_knowledge_mcp_server(
            knowledge_base_path=args.knowledge_base,
            embedding_base_url=args.ollama_base_url,
            reranker_device=args.reranker_device,
            reranker_local_files_only=args.reranker_local_files_only,
            database_url=database_url,
            demo_factory_root=demo_factory_root,
            telemetry=telemetry,
        )
        if args.transport == "stdio"
        else create_secure_knowledge_mcp_server(
            embedding_base_url=args.ollama_base_url,
            reranker_device=args.reranker_device,
            reranker_local_files_only=args.reranker_local_files_only,
            database_url=_require_knowledge_database_url(database_url),
            demo_factory_root=demo_factory_root,
            telemetry=telemetry,
        )
    )
    if args.transport == "stdio":
        server.run(transport="stdio")
        return
    assert telemetry is not None
    run_instrumented_mcp_http_server(
        server,
        host=args.host,
        port=args.port,
        streamable_http_path=KNOWLEDGE_MCP_HTTP_PATH,
        telemetry=telemetry,
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
    parser.add_argument(
        "--reranker-local-files-only",
        default=_environment_bool("KNOWLEDGE_MCP_RERANKER_LOCAL_FILES_ONLY", True),
        action=argparse.BooleanOptionalAction,
    )
    return parser.parse_args()


def _environment_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _required_knowledge_permission(tool_name: str) -> McpPermission:
    return _KNOWLEDGE_TOOL_PERMISSIONS[tool_name]


def _create_knowledge_telemetry() -> Telemetry:
    return configure_telemetry(
        TelemetryConfiguration(
            enabled=os.getenv("OTEL_ENABLED", "false").strip().lower()
            in {"1", "true", "yes", "on"},
            otlp_endpoint=os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "127.0.0.1:4317"),
            service_name=os.getenv("OTEL_SERVICE_NAME", "knowledge-mcp"),
        )
    )


def _invoke_knowledge_search(
    *, telemetry: Telemetry | None, action: Callable[[], Any]
) -> Any:
    if telemetry is None:
        return action()
    attributes = {
        "mcp.tool": "search_documentation",
        "mcp.operation": "read",
        "operation.type": "read",
        "retrieval.strategy": "hybrid_reranked",
    }
    started = perf_counter()
    status = "success"
    try:
        with telemetry.span("knowledge.search", attributes) as span:
            result = action()
            classifications = [item.classification for item in result.results]
            if classifications:
                telemetry.set_span_attributes(
                    span,
                    {"data.classification": max(classifications).name},
                )
            telemetry.set_span_attributes(
                span, {"retrieval.result_count": len(result.results)}
            )
        telemetry.log_event(event="mcp.server.completed", run_id=None)
        return result
    except BaseException as error:
        status = "failure"
        telemetry.log_error(
            event="mcp.server.failed",
            run_id=None,
            error_code=sanitized_error_code(error),
        )
        raise
    finally:
        telemetry.record_mcp_call(
            attributes={**attributes, "operation.status": status},
            duration_seconds=perf_counter() - started,
        )
        telemetry.record_retrieval(
            attributes={**attributes, "operation.status": status}
        )


def _documentation_search_for_request(
    *,
    ctx: Context | None,
    tool_name: str,
    fallback: DocumentationSearchCapability,
    access_control: McpHttpAccessControl | None,
    documentation_search_for_context: DocumentationSearchForContext | None,
) -> DocumentationSearchCapability:
    if access_control is None or documentation_search_for_context is None:
        return fallback
    if ctx is None:
        raise PermissionError("MCP authentication failed")
    access_context = access_control.access_context_from_headers(ctx.headers)
    access_control.authorize_tool(access_context, tool_name)
    return documentation_search_for_context(access_context.security_context)


def _require_knowledge_database_url(value: str | None) -> str:
    if not value:
        raise RuntimeError("KNOWLEDGE_DATABASE_URL is required for secure HTTP MCP")
    return value


if __name__ == "__main__":
    main()

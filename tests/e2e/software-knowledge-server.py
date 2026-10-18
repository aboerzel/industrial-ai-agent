"""Real MCP and RLS catalog with deterministic lexical test retrieval, no model."""

import os
import sys
from pathlib import Path

from industrial_ai_agent.domain.security import DataClassification, SecurityContext
from industrial_ai_agent.infrastructure.docling_ingestion import _chunk_document
from industrial_ai_agent.infrastructure.in_memory_lexical_knowledge_retriever import (
    InMemoryBm25KnowledgeRetriever,
)
from industrial_ai_agent.infrastructure.knowledge_mcp_server import (
    _required_knowledge_permission,
    create_knowledge_mcp_server,
)
from industrial_ai_agent.infrastructure.mcp_access_control import (
    create_demo_mcp_access_control,
)
from industrial_ai_agent.infrastructure.persistence.postgres import (
    PostgreSqlDocumentCatalogRepository,
    PostgreSqlSessionFactory,
)
from industrial_ai_agent.tools.documentation_search import DocumentationSearchCapability

factory = PostgreSqlSessionFactory(os.environ["FACTORY_DATABASE_URL"])
root = Path(os.environ["DOCUMENT_ROOT"]).resolve()


def for_context(context):
    documents = PostgreSqlDocumentCatalogRepository(factory, context).list_documents()
    chunks = []
    for doc in documents:
        source = (root / doc.file_path).resolve()
        assert source.is_relative_to(root)
        # Parsing/OCR is verified separately by KDEP; this fixture substitutes retrieval.
        content = (
            source.read_text(encoding="utf-8-sig")
            if source.suffix in {".md", ".txt"}
            else doc.title
        )
        chunks.extend(_chunk_document(doc, content))
    return DocumentationSearchCapability(InMemoryBm25KnowledgeRetriever(chunks))


async def listed_tools():
    return await server.list_tools()


server = create_knowledge_mcp_server(
    documentation_search=for_context(
        SecurityContext("fallback", ("fallback",), DataClassification.PUBLIC, False)
    ),
    access_control=create_demo_mcp_access_control(
        tools=listed_tools, required_permission=_required_knowledge_permission
    ),
    documentation_search_for_context=for_context,
)
server.run(
    transport="streamable-http",
    host="127.0.0.1",
    port=int(sys.argv[1]),
    streamable_http_path="/mcp",
)

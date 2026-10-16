"""Opt-in KDEP deployment proofs with real cached models, outside normal gates.

The caller starts the production command in a labelled disposable container on an
internal Docker network with only PostgreSQL and local Ollama reachable. No service
credentials enter test arguments or reports. See knowledge-runtime-dependencies.md.
"""

import json
import os
import subprocess
from collections.abc import Iterator

import pytest

pytestmark = pytest.mark.skipif(
    not os.getenv("KNOWLEDGE_TEST_IMAGE_ID"),
    reason="KDEP requires an explicit clean image and isolated offline deployment",
)


def _docker(*arguments: str, timeout: int = 180) -> str:
    result = subprocess.run(
        ["docker", *arguments],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=timeout,
    )
    if result.returncode:
        # Commands contain no secrets; startup/import tracebacks are useful evidence.
        pytest.fail(f"Docker proof failed ({result.returncode}): {result.stderr}")
    return result.stdout + result.stderr if arguments[0] == "logs" else result.stdout


@pytest.fixture(scope="module")
def image() -> str:
    image_id = os.environ["KNOWLEDGE_TEST_IMAGE_ID"]
    assert image_id.startswith("sha256:")
    return image_id


@pytest.fixture(scope="module")
def container(image: str) -> Iterator[str]:
    name = os.environ.get("KNOWLEDGE_TEST_CONTAINER")
    if not name:
        pytest.fail("KDEP requires an explicitly selected disposable container")
    details = json.loads(_docker("inspect", name))[0]
    assert details["Config"]["Labels"].get("industrial.knowledge-test") == "true"
    assert details["Image"] == image
    assert details["Config"]["Cmd"] == [
        "python",
        "-m",
        "industrial_ai_agent.infrastructure.knowledge_mcp_server",
        "--transport",
        "streamable-http",
        "--host",
        "0.0.0.0",
        "--port",
        "8002",
    ]
    yield name


def test_kdep_01_imports_production_entrypoint_and_full_retrieval_composition(
    image: str,
) -> None:
    _docker(
        "run",
        "--rm",
        "--network",
        "none",
        "--entrypoint",
        "python",
        image,
        "-c",
        "from industrial_ai_agent.infrastructure import knowledge_mcp_server, "
        "knowledge_retrieval_composition, docling_ingestion; "
        "from sentence_transformers import CrossEncoder; "
        "from transformers import PreTrainedModel; "
        "import torch, torchvision; print('KDEP-01 production imports passed')",
    )


def test_kdep_02_instantiates_real_cached_ingestion_embedding_and_reranking(
    container: str,
) -> None:
    _docker(
        "exec",
        container,
        "python",
        "-c",
        """
import math
import os
from pathlib import Path
from industrial_ai_agent.domain.security import DataClassification, SecurityContext
from industrial_ai_agent.infrastructure.docling_ingestion import DoclingDocumentIngestor
from industrial_ai_agent.infrastructure.knowledge_retrieval_composition import create_reranked_knowledge_retriever
from industrial_ai_agent.infrastructure.ollama_embedding_client import OllamaEmbeddingClient
from industrial_ai_agent.infrastructure.persistence.postgres import PostgreSqlDocumentCatalogRepository, PostgreSqlSessionFactory

sessions = PostgreSqlSessionFactory(os.environ['KNOWLEDGE_DATABASE_URL'])
try:
    context = SecurityContext('kdep-proof', ('test',), DataClassification.PUBLIC, True)
    documents = PostgreSqlDocumentCatalogRepository(sessions, context).list_documents()
    document = next(d for d in documents if d.document_id == 'doc-958096ad21a480be')
    chunks = DoclingDocumentIngestor(Path(os.environ['DOCUMENT_ROOT'])).ingest(document)
    assert chunks and all(c.document_id == document.document_id for c in chunks)
    embeddings = OllamaEmbeddingClient(base_url=os.environ['KNOWLEDGE_MCP_OLLAMA_BASE_URL'])
    vector = embeddings.embed_query('Factory Overview', classification=DataClassification.RESTRICTED)
    assert len(vector) >= 256 and all(math.isfinite(v) for v in vector)
    retriever = create_reranked_knowledge_retriever(
        chunks, embedding_base_url=os.environ['KNOWLEDGE_MCP_OLLAMA_BASE_URL'],
        query_classification=DataClassification.RESTRICTED,
        reranker_device='cpu', reranker_local_files_only=True,
    )
    results = retriever.search('Factory Overview', limit=1)
    assert results and results[0].document_id == document.document_id
    assert results[0].metadata['checksum'] == document.checksum
    print('KDEP-02 real parser, embedding vector and cross-encoder passed')
finally:
    sessions.dispose()
""",
        timeout=240,
    )


def test_kdep_03_production_container_is_healthy_and_protocol_ready(
    container: str,
) -> None:
    details = json.loads(_docker("inspect", container))[0]
    assert details["State"]["Running"]
    assert details["State"]["Health"]["Status"] == "healthy"
    assert details["RestartCount"] == 0
    _docker(
        "exec",
        container,
        "python",
        "-m",
        "industrial_ai_agent.infrastructure.mcp_readiness",
        "--url",
        "http://127.0.0.1:8002/mcp",
        "--bearer-token-env",
        "MCP_INDUSTRIAL_AGENT_TOKEN",
        "--required-tool",
        "search_documentation",
    )


def test_kdep_04_mcp_retrieval_preserves_fixture_provenance_and_clearance(
    container: str,
) -> None:
    _docker(
        "exec",
        container,
        "python",
        "-c",
        """
import asyncio
import os
from industrial_ai_agent.infrastructure.factory_mcp_client import StreamableHttpServerParameters, open_mcp_session

async def verify():
    for key, clearance in [('MCP_INDUSTRIAL_AGENT_PUBLIC_TOKEN', 0), ('MCP_INDUSTRIAL_AGENT_TOKEN', 2)]:
        transport = StreamableHttpServerParameters(
            url='http://127.0.0.1:8002/mcp', bearer_token=os.environ[key])
        async with open_mcp_session(transport) as session:
            await session.initialize()
            response = await session.call_tool('search_documentation', {'query':'S04 QUALITY-09 troubleshooting procedure', 'top_k':5})
            assert not response.is_error
            results = response.structured_content['results']
            assert results and all(r['classification'] <= clearance for r in results)
            assert all(r['source'] and r['chunk_id'].startswith(r['document_id'] + '::chunk-') for r in results)
            if clearance == 2:
                match = next(r for r in results if r['document_id'] == 'doc-s04quality09procedure')
                assert match['classification'] == 2 and 'QUALITY-09' in match['metadata']['fault_ids']
            else:
                assert all(r['document_id'] != 'doc-s04quality09procedure' for r in results)
    print('KDEP-04 authorized fixture, provenance and non-disclosure passed')

asyncio.run(verify())
""",
    )


def test_kdep_05_successful_startup_has_no_internet_or_cloud_credentials(
    container: str,
) -> None:
    details = json.loads(_docker("inspect", container))[0]
    networks = details["NetworkSettings"]["Networks"]
    assert networks
    for name in networks:
        assert json.loads(_docker("network", "inspect", name))[0]["Internal"]
    environment = dict(item.split("=", 1) for item in details["Config"]["Env"])
    assert environment.get("HF_HUB_OFFLINE") == "1"
    assert environment.get("TRANSFORMERS_OFFLINE") == "1"
    assert environment.get("KNOWLEDGE_MCP_RERANKER_LOCAL_FILES_ONLY") == "true"
    assert not any(
        environment.get(key)
        for key in (
            "GROQ_API_KEY",
            "MISTRAL_API_KEY",
            "NVIDIA_API_KEY",
            "OPENAI_API_KEY",
            "HF_TOKEN",
        )
    )
    assert details["State"]["Health"]["Status"] == "healthy"
    logs = _docker("logs", container).lower()
    assert "downloading" not in logs
    assert "initiating download" not in logs
    assert "download failed" not in logs
    assert "modulenotfounderror" not in logs
    assert "importerror" not in logs

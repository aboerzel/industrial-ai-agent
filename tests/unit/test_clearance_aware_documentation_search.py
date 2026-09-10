from concurrent.futures import ThreadPoolExecutor
from time import sleep
from typing import cast

import pytest

from industrial_ai_agent.domain.security import DataClassification, SecurityContext
from industrial_ai_agent.infrastructure.knowledge_mcp_server import (
    ClearanceAwareDocumentationSearchFactory,
)
from industrial_ai_agent.tools.documentation_search import DocumentationSearchCapability


def _context(clearance: DataClassification) -> SecurityContext:
    return SecurityContext(
        subject_id=f"test-{clearance.name.lower()}",
        roles=("test",),
        clearance=clearance,
        authenticated=True,
    )


def test_retrieval_cache_never_reuses_a_higher_clearance_pipeline(
    monkeypatch,
    tmp_path,
) -> None:
    factory = ClearanceAwareDocumentationSearchFactory(
        database_url="postgresql://unused-for-this-unit-test",
        embedding_base_url=None,
        reranker_device=None,
        reranker_local_files_only=True,
        document_root=tmp_path,
    )
    built_for: list[SecurityContext] = []

    def build(context: SecurityContext) -> DocumentationSearchCapability:
        built_for.append(context)
        return cast(DocumentationSearchCapability, object())

    monkeypatch.setattr(factory, "_build", build)
    confidential = _context(DataClassification.CONFIDENTIAL)
    internal = _context(DataClassification.INTERNAL)

    confidential_pipeline = factory.for_context(confidential)
    internal_pipeline = factory.for_context(internal)

    assert confidential_pipeline is not internal_pipeline
    assert factory.for_context(internal) is internal_pipeline
    assert built_for == [confidential, internal]


def test_warm_up_builds_all_authorized_demo_projections_once(
    monkeypatch, tmp_path
) -> None:
    factory = ClearanceAwareDocumentationSearchFactory(
        database_url="postgresql://unused-for-this-unit-test",
        embedding_base_url=None,
        reranker_device=None,
        reranker_local_files_only=True,
        document_root=tmp_path,
    )
    built_for: list[SecurityContext] = []

    def build(context: SecurityContext) -> DocumentationSearchCapability:
        built_for.append(context)
        return cast(DocumentationSearchCapability, object())

    monkeypatch.setattr(factory, "_build", build)

    factory.warm_up()
    factory.for_context(
        SecurityContext(
            subject_id="industrial-agent",
            roles=("industrial-agent",),
            clearance=DataClassification.CONFIDENTIAL,
            authenticated=True,
        )
    )

    assert [(context.subject_id, context.clearance) for context in built_for] == [
        ("industrial-agent-public", DataClassification.PUBLIC),
        ("industrial-agent-internal", DataClassification.INTERNAL),
        ("industrial-agent", DataClassification.CONFIDENTIAL),
        ("industrial-agent-restricted", DataClassification.RESTRICTED),
    ]


def test_concurrent_first_requests_build_one_context_pipeline(
    monkeypatch, tmp_path
) -> None:
    factory = ClearanceAwareDocumentationSearchFactory(
        database_url="postgresql://unused-for-this-unit-test",
        embedding_base_url=None,
        reranker_device=None,
        reranker_local_files_only=True,
        document_root=tmp_path,
    )
    build_count = 0

    def build(_: SecurityContext) -> DocumentationSearchCapability:
        nonlocal build_count
        build_count += 1
        sleep(0.01)
        return cast(DocumentationSearchCapability, object())

    monkeypatch.setattr(factory, "_build", build)
    context = _context(DataClassification.CONFIDENTIAL)
    with ThreadPoolExecutor(max_workers=4) as executor:
        pipelines = list(executor.map(factory.for_context, (context,) * 4))

    assert build_count == 1
    assert len({id(pipeline) for pipeline in pipelines}) == 1


def test_shared_reranker_is_initialized_once(monkeypatch, tmp_path) -> None:
    factory = ClearanceAwareDocumentationSearchFactory(
        database_url="postgresql://unused-for-this-unit-test",
        embedding_base_url=None,
        reranker_device=None,
        reranker_local_files_only=True,
        document_root=tmp_path,
    )
    initialized = 0

    class FakeCrossEncoderReranker:
        def __init__(self, **_kwargs) -> None:
            nonlocal initialized
            initialized += 1

        def rerank(self, _query, candidates):
            return tuple(candidates)

    monkeypatch.setattr(
        "industrial_ai_agent.infrastructure.sentence_transformers_reranker.SentenceTransformersCrossEncoderReranker",
        FakeCrossEncoderReranker,
    )

    assert factory._shared_reranker() is factory._shared_reranker()
    assert initialized == 1


def test_shared_docling_ingestor_is_initialized_once(monkeypatch, tmp_path) -> None:
    factory = ClearanceAwareDocumentationSearchFactory(
        database_url="postgresql://unused-for-this-unit-test",
        embedding_base_url=None,
        reranker_device=None,
        reranker_local_files_only=True,
        document_root=tmp_path,
    )
    initialized = 0

    class FakeDoclingDocumentIngestor:
        def __init__(self, _document_root) -> None:
            nonlocal initialized
            initialized += 1

    monkeypatch.setattr(
        "industrial_ai_agent.infrastructure.docling_ingestion.DoclingDocumentIngestor",
        FakeDoclingDocumentIngestor,
    )

    assert factory._shared_ingestor() is factory._shared_ingestor()
    assert initialized == 1


def test_warm_up_propagates_a_required_pipeline_failure(monkeypatch, tmp_path) -> None:
    factory = ClearanceAwareDocumentationSearchFactory(
        database_url="postgresql://unused-for-this-unit-test",
        embedding_base_url=None,
        reranker_device=None,
        reranker_local_files_only=True,
        document_root=tmp_path,
    )

    def fail(_: SecurityContext) -> DocumentationSearchCapability:
        raise RuntimeError("required retrieval pipeline unavailable")

    monkeypatch.setattr(factory, "_build", fail)

    with pytest.raises(RuntimeError, match="required retrieval pipeline unavailable"):
        factory.warm_up()

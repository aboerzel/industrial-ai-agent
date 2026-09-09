from typing import cast

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

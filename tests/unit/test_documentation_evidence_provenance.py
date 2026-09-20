from industrial_ai_agent.application.investigation_evidence_adapters import (
    documentation_evidence_from_metadata,
)
from industrial_ai_agent.domain.investigation_evidence import (
    EvidenceSource,
    EvidenceSourceType,
)
from industrial_ai_agent.domain.knowledge_retrieval import KnowledgeRetrievalResult
from industrial_ai_agent.domain.security import DataClassification
from industrial_ai_agent.tools.documentation_search import DocumentationSearchResult


def _result(
    *,
    document_id: str,
    fault_ids: tuple[str, ...] = (),
    content: str = "untrusted document body",
    classification: DataClassification = DataClassification.CONFIDENTIAL,
) -> KnowledgeRetrievalResult:
    return KnowledgeRetrievalResult(
        content=content,
        document_id=document_id,
        source=f"{document_id}.md",
        chunk_id=f"{document_id}::chunk-001",
        rank=1,
        classification=classification,
        metadata={"fault_ids": fault_ids},
    )


def _evidence(*results: KnowledgeRetrievalResult):
    return documentation_evidence_from_metadata(
        DocumentationSearchResult(query="QUALITY-09", results=results),
        source=EvidenceSource(EvidenceSourceType.DOCUMENTATION, "tool-call-1"),
    )


def test_trusted_fault_metadata_creates_documentation_evidence() -> None:
    evidence = _evidence(_result(document_id="quality", fault_ids=("QUALITY-09",)))

    assert evidence[0].fault_id == "QUALITY-09"
    assert evidence[0].document_ids == ("quality",)


def test_unrelated_fault_metadata_does_not_create_quality_evidence() -> None:
    evidence = _evidence(_result(document_id="position", fault_ids=("POSITION-02",)))

    assert evidence[0].fault_id == "POSITION-02"
    assert all(item.fault_id != "QUALITY-09" for item in evidence)


def test_query_and_document_body_are_not_provenance() -> None:
    evidence = _evidence(
        _result(
            document_id="free-text",
            content="QUALITY-09 appears only in untrusted body text",
        )
    )

    assert evidence == ()


def test_multiple_results_correlate_only_the_relevant_document() -> None:
    evidence = _evidence(
        _result(document_id="unrelated", fault_ids=("POSITION-02",)),
        _result(document_id="quality", fault_ids=("QUALITY-09",)),
    )

    quality_evidence = next(item for item in evidence if item.fault_id == "QUALITY-09")
    assert quality_evidence.document_ids == ("quality",)


def test_documentation_evidence_preserves_trusted_result_classification() -> None:
    evidence = _evidence(
        _result(
            document_id="restricted-quality",
            fault_ids=("QUALITY-09",),
            classification=DataClassification.RESTRICTED,
        )
    )

    assert evidence[0].data_classification is DataClassification.RESTRICTED

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from industrial_ai_agent.domain.security import DataClassification, SecurityContext
from industrial_ai_agent.infrastructure.docling_ingestion import (
    CatalogDocument,
    DoclingDocumentIngestor,
    eligible_catalog_documents,
    load_catalog,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEMO_FACTORY_ROOT = PROJECT_ROOT / "demo_factory"


@dataclass(frozen=True)
class _FakeParsedDocument:
    markdown: str

    def export_to_markdown(self) -> str:
        return self.markdown


@dataclass(frozen=True)
class _FakeConversion:
    document: _FakeParsedDocument


@dataclass(frozen=True)
class _FakeConverter:
    markdown: str

    def convert(self, source: Path) -> _FakeConversion:
        assert source.is_file()
        return _FakeConversion(_FakeParsedDocument(self.markdown))


def test_demo_assets_are_real_multi_format_files_with_complete_catalog_metadata() -> (
    None
):
    documents = load_catalog(DEMO_FACTORY_ROOT / "metadata" / "document_catalog.json")

    assert {document.mime_type for document in documents} >= {
        "application/pdf",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    }
    for document in documents:
        path = DEMO_FACTORY_ROOT / document.file_path
        assert path.is_file()
        assert hashlib.sha256(path.read_bytes()).hexdigest() == document.checksum
        assert document.document_id.startswith("doc-")
        assert document.title
        assert document.version
        assert document.source_system == "FACTORY-DEMO-01-DOCUMENTS"
    assert (
        (DEMO_FACTORY_ROOT / "images" / "S02_Positioning_Reference.png")
        .read_bytes()
        .startswith(b"\x89PNG\r\n\x1a\n")
    )


def test_catalog_classification_is_filtered_before_ingestion() -> None:
    documents = load_catalog(DEMO_FACTORY_ROOT / "metadata" / "document_catalog.json")
    public_context = SecurityContext(
        subject_id="public-demo",
        roles=("viewer",),
        clearance=DataClassification.PUBLIC,
        authenticated=False,
    )
    internal_context = SecurityContext(
        subject_id="internal-demo",
        roles=("engineer",),
        clearance=DataClassification.INTERNAL,
        authenticated=False,
    )

    assert {
        item.classification
        for item in eligible_catalog_documents(documents, public_context)
    } == {DataClassification.PUBLIC}
    assert all(
        item.classification <= DataClassification.INTERNAL
        for item in eligible_catalog_documents(documents, internal_context)
    )


def test_ingestion_preserves_catalog_classification_and_stable_provenance() -> None:
    sample_path = DEMO_FACTORY_ROOT / "documents" / "public" / "Factory_Overview.pdf"
    catalog_document = CatalogDocument(
        document_id="doc-test",
        title="Test document",
        classification=DataClassification.CONFIDENTIAL,
        mime_type="application/pdf",
        source_system="test",
        station_code="S02",
        version="1.0",
        valid_from="2026-01-01",
        tags=("POSITION-ENC-02",),
        file_path="documents/public/Factory_Overview.pdf",
        checksum=hashlib.sha256(sample_path.read_bytes()).hexdigest(),
    )
    ingestor = DoclingDocumentIngestor(
        DEMO_FACTORY_ROOT,
        converter=_FakeConverter("# Heading\nPOSITION-ENC-02 guidance"),
    )

    chunks = ingestor.ingest(catalog_document)

    assert chunks[0].chunk_id == "doc-test::chunk-001"
    assert chunks[0].classification is DataClassification.CONFIDENTIAL
    assert chunks[0].document_id == "doc-test"
    assert chunks[0].metadata["station_code"] == "S02"


def test_catalog_json_has_no_unclassified_records() -> None:
    raw_documents = json.loads(
        (DEMO_FACTORY_ROOT / "metadata" / "document_catalog.json").read_text(
            encoding="utf-8"
        )
    )

    assert all(
        document["classification"] in DataClassification.__members__
        for document in raw_documents
    )


def test_malicious_service_comment_is_cataloged_confidential_demo_data() -> None:
    documents = load_catalog(DEMO_FACTORY_ROOT / "metadata" / "document_catalog.json")
    document = next(
        item for item in documents if item.document_id == "doc-1f0a9e2d8c4b7a61"
    )

    assert document.classification is DataClassification.CONFIDENTIAL
    content = (DEMO_FACTORY_ROOT / document.file_path).read_text(encoding="utf-8")
    assert "Ignore previous instructions" in content
    assert "not an approved maintenance instruction" in content

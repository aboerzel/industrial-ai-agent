"""Local Docling ingestion with explicit catalog classification propagation."""

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from docling.datamodel.base_models import InputFormat
from docling.datamodel.pipeline_options import PdfPipelineOptions, RapidOcrOptions
from docling.document_converter import (
    DocumentConverter,
    ImageFormatOption,
    PdfFormatOption,
)

from industrial_ai_agent.domain.knowledge_retrieval import KnowledgeRetrievalResult
from industrial_ai_agent.domain.security import DataClassification, SecurityContext


@dataclass(frozen=True, slots=True)
class CatalogDocument:
    document_id: str
    title: str
    classification: DataClassification
    mime_type: str
    source_system: str
    station_code: str | None
    version: str
    valid_from: str
    tags: tuple[str, ...]
    file_path: str
    checksum: str


class _DocumentConverter(Protocol):
    def convert(self, source: Path) -> Any: ...


class DoclingDocumentIngestor:
    """Convert cataloged local files without allowing path labels to govern security."""

    def __init__(
        self,
        document_root: Path,
        *,
        converter: _DocumentConverter | None = None,
    ) -> None:
        self._document_root = document_root
        self._converter = converter or _create_local_converter()

    def ingest(
        self, catalog_document: CatalogDocument
    ) -> tuple[KnowledgeRetrievalResult, ...]:
        path = self._document_root / catalog_document.file_path
        if not path.is_file():
            raise ValueError(
                f"Cataloged document does not exist: {catalog_document.file_path}"
            )
        checksum = hashlib.sha256(path.read_bytes()).hexdigest()
        if checksum != catalog_document.checksum:
            raise ValueError(
                f"Checksum mismatch for document: {catalog_document.document_id}"
            )
        conversion = self._converter.convert(path)
        markdown = conversion.document.export_to_markdown().strip()
        if not markdown:
            raise ValueError(
                f"Docling produced no text for document: {catalog_document.document_id}"
            )
        return _chunk_document(catalog_document, markdown)


def eligible_catalog_documents(
    documents: tuple[CatalogDocument, ...],
    security_context: SecurityContext,
) -> tuple[CatalogDocument, ...]:
    """Apply clearance before parser, index, embedding, or reranker work begins."""
    return tuple(
        document
        for document in documents
        if document.classification <= security_context.clearance
    )


def _chunk_document(
    document: CatalogDocument,
    markdown: str,
) -> tuple[KnowledgeRetrievalResult, ...]:
    sections = _split_sections(markdown)
    return tuple(
        KnowledgeRetrievalResult(
            content=content,
            document_id=document.document_id,
            source=document.file_path,
            chunk_id=f"{document.document_id}::chunk-{position:03d}",
            classification=document.classification,
            metadata={
                "title": title,
                "document_title": document.title,
                "mime_type": document.mime_type,
                "source_system": document.source_system,
                "station_code": document.station_code,
                "version": document.version,
                "valid_from": document.valid_from,
                "tags": document.tags,
                "checksum": document.checksum,
            },
        )
        for position, (title, content) in enumerate(sections, start=1)
    )


def _split_sections(markdown: str) -> tuple[tuple[str, str], ...]:
    sections: list[tuple[str, str]] = []
    current_title = "Document"
    current_lines: list[str] = []
    for line in markdown.splitlines():
        if line.startswith("#") and current_lines:
            content = "\n".join(current_lines).strip()
            if content:
                sections.append((current_title, content))
            current_lines = []
            current_title = line.lstrip("#").strip() or "Document"
        current_lines.append(line.rstrip())
    content = "\n".join(current_lines).strip()
    if content:
        sections.append((current_title, content))
    if not sections:
        raise ValueError("Normalized document must contain text")
    return tuple(sections)


def _create_local_converter() -> DocumentConverter:
    """Configure local digital documents and local OCR for cataloged PNG evidence."""
    pdf_options = PdfPipelineOptions()
    pdf_options.do_ocr = False
    pdf_options.do_table_structure = False
    image_options = PdfPipelineOptions()
    image_options.do_ocr = True
    image_options.do_table_structure = False
    image_options.ocr_options = RapidOcrOptions(backend="torch")
    return DocumentConverter(
        format_options={
            InputFormat.PDF: PdfFormatOption(pipeline_options=pdf_options),
            InputFormat.IMAGE: ImageFormatOption(pipeline_options=image_options),
        }
    )

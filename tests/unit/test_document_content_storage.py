import re
from pathlib import Path

import pytest

from industrial_ai_agent.infrastructure.persistence.postgres import (
    PostgreSqlDocumentContentRepository,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _reader(document_root: Path) -> PostgreSqlDocumentContentRepository:
    return PostgreSqlDocumentContentRepository(object(), document_root)  # type: ignore[arg-type]


def test_catalog_content_path_is_confined_to_the_configured_document_root(
    tmp_path: Path,
) -> None:
    document_root = tmp_path / "document-content"
    source = document_root / "documents" / "confidential" / "procedure.md"
    source.parent.mkdir(parents=True)
    source.write_text("authorized", encoding="utf-8")
    reader = _reader(document_root)

    assert (
        reader._catalog_path("documents/confidential/procedure.md") == source.resolve()
    )
    assert reader._catalog_path("../outside.md") is None
    assert reader._catalog_path("documents/../outside.md") is None
    assert reader._catalog_path("/tmp/outside.md") is None
    assert reader._catalog_path("C:/outside.md") is None
    assert reader._catalog_path("documents\\confidential\\procedure.md") is None


def test_catalog_content_path_rejects_symlink_escape_and_missing_storage(
    tmp_path: Path,
) -> None:
    document_root = tmp_path / "document-content"
    (document_root / "documents").mkdir(parents=True)
    outside = tmp_path / "outside.md"
    outside.write_text("outside", encoding="utf-8")
    link = document_root / "documents" / "escaped.md"
    try:
        link.symlink_to(outside)
    except OSError:
        pytest.skip("symlink creation is unavailable on this platform")
    reader = _reader(document_root)

    assert reader._catalog_path("documents/escaped.md") is None
    assert _reader(tmp_path / "missing")._catalog_path("documents/missing.md") is None


def test_catalog_content_path_accepts_cataloged_image_documents(
    tmp_path: Path,
) -> None:
    document_root = tmp_path / "document-content"
    source = document_root / "images" / "inspection.png"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"authorized image")

    assert (
        _reader(document_root)._catalog_path("images/inspection.png")
        == source.resolve()
    )


def test_container_images_do_not_bake_document_content_and_compose_mounts_read_only() -> (
    None
):
    dockerfiles = tuple(PROJECT_ROOT.glob("Dockerfile*"))
    compose = (PROJECT_ROOT / "compose.yaml").read_text(encoding="utf-8")

    assert dockerfiles
    assert all(
        re.search(
            r"^(?:COPY|ADD)\s+(?:[^\s]+/)?(?:demo_factory|knowledge_base)(?:\s|/)",
            dockerfile.read_text(encoding="utf-8"),
            flags=re.MULTILINE,
        )
        is None
        for dockerfile in dockerfiles
    )
    assert compose.count(":/app/data/document-content/documents:ro") == 2
    assert compose.count(":/app/data/document-content/images:ro") == 2
    assert ":/app/data/factory/metadata:ro" in compose
    assert ":/app/data/knowledge:ro" in compose
    assert "FACTORY_DATA_ROOT: /app/data/factory" in compose
    assert "DOCUMENT_ROOT: /app/data/document-content" in compose
    assert "KNOWLEDGE_ROOT: /app/data/knowledge" in compose

"""Explicit PostgreSQL integration coverage for migrations, seed records, and RLS."""

import os
from pathlib import Path
from zipfile import ZipFile

import pytest
from sqlalchemy import select, text

from industrial_ai_agent.domain.product_history import ProductId, ProductionStepStatus
from industrial_ai_agent.domain.security import DataClassification, SecurityContext
from industrial_ai_agent.infrastructure.persistence.models import (
    MaintenanceEventRecord,
    ProcessParameterRecord,
    ProductEventRecord,
    ProductRecord,
)
from industrial_ai_agent.infrastructure.persistence.postgres import (
    PostgreSqlDocumentCatalogRepository,
    PostgreSqlProductHistoryRepository,
    PostgreSqlSessionFactory,
)

DATABASE_URL = os.getenv("FACTORY_DATABASE_URL")
PROJECT_ROOT = Path(__file__).resolve().parents[2]
pytestmark = pytest.mark.skipif(
    not DATABASE_URL,
    reason="requires FACTORY_DATABASE_URL for the local PostgreSQL integration service",
)


def _context(clearance: DataClassification) -> SecurityContext:
    return SecurityContext(
        subject_id=f"integration-{clearance.name.lower()}",
        roles=("test-engineer",),
        clearance=clearance,
        authenticated=False,
    )


def _count(
    factory: PostgreSqlSessionFactory, clearance: DataClassification, table: str
) -> int:
    with factory.connection(_context(clearance)) as connection:
        return int(
            connection.execute(text(f"SELECT count(*) FROM {table}")).scalar_one()
        )


def test_application_role_rls_enforces_clearance_without_repository_filtering() -> None:
    assert DATABASE_URL is not None
    session_factory = PostgreSqlSessionFactory(DATABASE_URL)
    try:
        assert _count(session_factory, DataClassification.PUBLIC, "product") == 0
        assert (
            _count(session_factory, DataClassification.PUBLIC, "document_catalog") == 3
        )
        assert (
            _count(session_factory, DataClassification.INTERNAL, "document_catalog")
            == 6
        )
        assert _count(session_factory, DataClassification.CONFIDENTIAL, "product") == 5
        assert (
            _count(
                session_factory, DataClassification.CONFIDENTIAL, "process_parameter"
            )
            == 0
        )
        assert (
            _count(session_factory, DataClassification.RESTRICTED, "process_parameter")
            == 1
        )
    finally:
        session_factory.dispose()


def test_application_role_has_no_rls_bypass_attribute() -> None:
    assert DATABASE_URL is not None
    session_factory = PostgreSqlSessionFactory(DATABASE_URL)
    try:
        with session_factory.connection(
            _context(DataClassification.RESTRICTED)
        ) as connection:
            bypass_rls = connection.execute(
                text("SELECT rolbypassrls FROM pg_roles WHERE rolname = current_user")
            ).scalar_one()
    finally:
        session_factory.dispose()

    assert bypass_rls is False


def test_schema_seed_and_repository_mapping_are_available_to_application_role() -> None:
    assert DATABASE_URL is not None
    session_factory = PostgreSqlSessionFactory(DATABASE_URL)
    confidential_context = _context(DataClassification.CONFIDENTIAL)
    try:
        with session_factory.connection(confidential_context) as connection:
            tables = (
                connection.execute(
                    text(
                        "SELECT to_regclass(table_name) FROM unnest(ARRAY["
                        "'factory', 'station', 'product', 'production_order', "
                        "'product_event', 'machine_state', 'alarm_event', "
                        "'quality_inspection', 'maintenance_event', "
                        "'maintenance_ticket', 'process_parameter', "
                        "'document_catalog']) AS table_name"
                    )
                )
                .scalars()
                .all()
            )
        history = PostgreSqlProductHistoryRepository(
            session_factory, confidential_context
        ).get_product_history(ProductId("P4711"))
        documents = PostgreSqlDocumentCatalogRepository(
            session_factory, confidential_context
        ).list_documents()
    finally:
        session_factory.dispose()

    assert all(tables)
    assert history is not None
    assert history.classification is DataClassification.CONFIDENTIAL
    assert history.steps[1].status is ProductionStepStatus.WARNING
    assert history.steps[-1].error_code == "QUALITY-09"
    assert len(documents) == 10
    assert all(
        document.classification <= DataClassification.CONFIDENTIAL
        for document in documents
    )


def test_orm_seed_and_catalog_tell_one_synthetic_factory_story() -> None:
    """Guard the data links that make the portfolio documents operationally useful."""
    assert DATABASE_URL is not None
    session_factory = PostgreSqlSessionFactory(DATABASE_URL)
    try:
        with session_factory.session(
            _context(DataClassification.RESTRICTED)
        ) as session:
            product_codes = set(
                session.scalars(
                    select(ProductRecord.product_code).where(
                        ProductRecord.product_code.in_(
                            ("P4711", "P4801", "P4802", "P4805", "P4811")
                        )
                    )
                )
            )
            positioning_events = tuple(
                session.scalars(
                    select(ProductEventRecord).where(
                        ProductEventRecord.error_code == "POSITION-ENC-02"
                    )
                )
            )
            maintenance_actions = set(
                session.scalars(select(MaintenanceEventRecord.action))
            )
            process_parameter = session.scalar(
                select(ProcessParameterRecord).where(
                    ProcessParameterRecord.parameter_name == "robot_trajectory_limit"
                )
            )
    finally:
        session_factory.dispose()

    asset_text = _demo_asset_text()
    assert product_codes == {"P4711", "P4801", "P4802", "P4805", "P4811"}
    assert len(positioning_events) == 5
    assert maintenance_actions == {
        "encoder replacement",
        "homing",
        "dry cycle",
        "inspection verification",
        "return to service",
    }
    assert process_parameter is not None
    assert process_parameter.parameter_value == "12.5 mm/s"
    for identifier in (
        "FACTORY-DEMO-01",
        "S02",
        "S04",
        "POSITION-ENC-02",
        "QUALITY-09",
        "MT-S02-20260117",
        "robot_trajectory_limit",
    ):
        assert identifier in asset_text


def _demo_asset_text() -> str:
    root = PROJECT_ROOT / "demo_factory" / "documents"
    pdf_text = (
        root / "confidential" / "Positioning_Error_Troubleshooting.pdf"
    ).read_text(encoding="latin-1")
    zipped_text = ""
    for path in (
        root / "confidential" / "Maintenance_Report_S02.docx",
        root / "confidential" / "Failure_Analysis_S02.pptx",
        root / "restricted" / "Process_Recipe.xlsx",
    ):
        with ZipFile(path) as archive:
            zipped_text += "".join(
                archive.read(name).decode("utf-8", errors="ignore")
                for name in archive.namelist()
                if name.endswith(".xml")
            )
    return pdf_text + zipped_text

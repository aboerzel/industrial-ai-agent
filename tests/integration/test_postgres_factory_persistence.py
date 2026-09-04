"""Explicit PostgreSQL integration coverage for migrations, seed records, and RLS."""

import os

import pytest
from sqlalchemy import text

from industrial_ai_agent.domain.product_history import ProductId, ProductionStepStatus
from industrial_ai_agent.domain.security import DataClassification, SecurityContext
from industrial_ai_agent.infrastructure.persistence.postgres import (
    PostgreSqlDocumentCatalogRepository,
    PostgreSqlProductHistoryRepository,
    PostgreSqlSessionFactory,
)

DATABASE_URL = os.getenv("FACTORY_DATABASE_URL")
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

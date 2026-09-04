"""SQLAlchemy 2.x PostgreSQL adapters with transaction-scoped RLS clearance."""

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime

from sqlalchemy import Connection, Engine, create_engine, text

from industrial_ai_agent.domain.machine_status import MachineState, MachineStatus
from industrial_ai_agent.domain.product_history import (
    ProductHistory,
    ProductId,
    ProductionStep,
    ProductionStepStatus,
    StationId,
)
from industrial_ai_agent.domain.security import DataClassification, SecurityContext


class PostgreSqlSessionFactory:
    """Owns only the non-privileged application database connection lifecycle."""

    def __init__(self, database_url: str) -> None:
        if not database_url.strip():
            raise ValueError("database_url must not be empty")
        self._engine: Engine = create_engine(database_url, pool_pre_ping=True)

    @contextmanager
    def connection(self, security_context: SecurityContext) -> Iterator[Connection]:
        with self._engine.begin() as connection:
            # set_config is parameterized and transaction-local, unlike interpolated SET.
            connection.execute(
                text("SELECT set_config('app.clearance', :clearance, true)"),
                {"clearance": str(int(security_context.clearance))},
            )
            yield connection

    def dispose(self) -> None:
        self._engine.dispose()


class PostgreSqlProductHistoryRepository:
    """Map classified persistent production events to the existing Domain model."""

    def __init__(
        self,
        session_factory: PostgreSqlSessionFactory,
        security_context: SecurityContext,
    ) -> None:
        self._session_factory = session_factory
        self._security_context = security_context

    def get_product_history(self, product_id: ProductId) -> ProductHistory | None:
        with self._session_factory.connection(self._security_context) as connection:
            product = (
                connection.execute(
                    text(
                        "SELECT id, product_code, classification FROM product "
                        "WHERE product_code = :product_code"
                    ),
                    {"product_code": product_id.value},
                )
                .mappings()
                .one_or_none()
            )
            if product is None:
                return None
            events = connection.execute(
                text(
                    """
                    SELECT station.code, product_event.event_at, product_event.status,
                           product_event.error_code, product_event.classification
                    FROM product_event
                    JOIN station ON station.id = product_event.station_id
                    WHERE product_event.product_id = :product_id
                    ORDER BY product_event.event_at
                    """
                ),
                {"product_id": product["id"]},
            ).mappings()
            event_rows = tuple(events)
            classification = max(
                DataClassification(product["classification"]),
                *(DataClassification(event["classification"]) for event in event_rows),
            )
            return ProductHistory(
                product_id=ProductId(product["product_code"]),
                classification=classification,
                steps=tuple(
                    ProductionStep(
                        station_id=StationId(event["code"]),
                        timestamp=_as_datetime(event["event_at"]),
                        status=ProductionStepStatus(event["status"]),
                        error_code=event["error_code"],
                    )
                    for event in event_rows
                ),
            )


class PostgreSqlMachineStatusRepository:
    """Read the latest RLS-filtered state for one station."""

    def __init__(
        self,
        session_factory: PostgreSqlSessionFactory,
        security_context: SecurityContext,
    ) -> None:
        self._session_factory = session_factory
        self._security_context = security_context

    def get_machine_status(self, station_id: StationId) -> MachineStatus | None:
        with self._session_factory.connection(self._security_context) as connection:
            row = (
                connection.execute(
                    text(
                        """
                    SELECT station.code, machine_state.state, machine_state.active_error_code,
                           machine_state.classification
                    FROM machine_state
                    JOIN station ON station.id = machine_state.station_id
                    WHERE station.code = :station_code
                    ORDER BY machine_state.observed_at DESC
                    LIMIT 1
                    """
                    ),
                    {"station_code": station_id.value},
                )
                .mappings()
                .one_or_none()
            )
            if row is None:
                return None
            return MachineStatus(
                station_id=StationId(row["code"]),
                state=MachineState(row["state"]),
                active_error_code=row["active_error_code"],
                classification=DataClassification(row["classification"]),
            )


class PostgreSqlDocumentCatalogRepository:
    """Read RLS-filtered document metadata without exposing SQL types to retrieval."""

    def __init__(
        self,
        session_factory: PostgreSqlSessionFactory,
        security_context: SecurityContext,
    ) -> None:
        self._session_factory = session_factory
        self._security_context = security_context

    def list_documents(self):
        from industrial_ai_agent.infrastructure.docling_ingestion import CatalogDocument

        with self._session_factory.connection(self._security_context) as connection:
            rows = connection.execute(
                text(
                    """
                    SELECT document_catalog.id, document_catalog.title,
                           document_catalog.classification, document_catalog.mime_type,
                           document_catalog.source_system, station.code AS station_code,
                           document_catalog.version, document_catalog.valid_from,
                           document_catalog.tags, document_catalog.file_path,
                           document_catalog.checksum
                    FROM document_catalog
                    LEFT JOIN station ON station.id = document_catalog.station_id
                    ORDER BY document_catalog.file_path
                    """
                )
            ).mappings()
            return tuple(
                CatalogDocument(
                    document_id=str(row["id"]),
                    title=row["title"],
                    classification=DataClassification(row["classification"]),
                    mime_type=row["mime_type"],
                    source_system=row["source_system"],
                    station_code=row["station_code"],
                    version=row["version"],
                    valid_from=row["valid_from"].isoformat(),
                    tags=tuple(row["tags"]),
                    file_path=row["file_path"],
                    checksum=row["checksum"],
                )
                for row in rows
            )


def _as_datetime(value: object) -> datetime:
    if not isinstance(value, datetime):
        raise TypeError("PostgreSQL event_at must be a datetime")
    return value

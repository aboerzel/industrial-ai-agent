"""SQLAlchemy 2.x PostgreSQL adapters with transaction-scoped RLS clearance."""

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import Connection, Engine, create_engine, select, text
from sqlalchemy.orm import Session, joinedload, sessionmaker

from industrial_ai_agent.domain.machine_status import MachineState, MachineStatus
from industrial_ai_agent.domain.product_history import (
    ProductHistory,
    ProductId,
    ProductionStep,
    ProductionStepStatus,
    StationId,
)
from industrial_ai_agent.domain.security import DataClassification, SecurityContext
from industrial_ai_agent.infrastructure.persistence.models import (
    DocumentCatalogRecord,
    MachineStateRecord,
    ProductEventRecord,
    ProductRecord,
)


class PostgreSqlSessionFactory:
    """Own only the non-privileged application Session lifecycle and RLS context."""

    def __init__(self, database_url: str) -> None:
        if not database_url.strip():
            raise ValueError("database_url must not be empty")
        self._engine: Engine = create_engine(database_url, pool_pre_ping=True)
        self._sessions = sessionmaker(self._engine, expire_on_commit=False)

    @contextmanager
    def session(self, security_context: SecurityContext) -> Iterator[Session]:
        with self._sessions() as session, session.begin():
            # PostgreSQL-specific security context: parameterized and transaction-local.
            session.execute(
                text("SELECT set_config('app.clearance', :clearance, true)"),
                {"clearance": str(int(security_context.clearance))},
            )
            yield session

    def dispose(self) -> None:
        self._engine.dispose()

    @contextmanager
    def connection(self, security_context: SecurityContext) -> Iterator[Connection]:
        """Expose a transaction-scoped connection only for RLS integration assertions."""
        with self.session(security_context) as session:
            yield session.connection()


class PostgreSqlProductHistoryRepository:
    """Map RLS-filtered ORM records to the existing Domain product-history model."""

    def __init__(
        self,
        session_factory: PostgreSqlSessionFactory,
        security_context: SecurityContext,
    ) -> None:
        self._session_factory = session_factory
        self._security_context = security_context

    def get_product_history(self, product_id: ProductId) -> ProductHistory | None:
        with self._session_factory.session(self._security_context) as session:
            product = session.scalar(
                select(ProductRecord).where(
                    ProductRecord.product_code == product_id.value
                )
            )
            if product is None:
                return None
            events = tuple(
                session.scalars(
                    select(ProductEventRecord)
                    .options(joinedload(ProductEventRecord.station))
                    .where(ProductEventRecord.product_id == product.id)
                    .order_by(ProductEventRecord.event_at)
                )
            )
        classification = max(
            DataClassification(product.classification),
            *(DataClassification(event.classification) for event in events),
        )
        return ProductHistory(
            product_id=ProductId(product.product_code),
            classification=classification,
            steps=tuple(
                ProductionStep(
                    station_id=StationId(event.station.code),
                    timestamp=event.event_at,
                    status=ProductionStepStatus(event.status),
                    error_code=event.error_code,
                )
                for event in events
            ),
        )


class PostgreSqlMachineStatusRepository:
    """Read the latest RLS-filtered ORM machine state for one station."""

    def __init__(
        self,
        session_factory: PostgreSqlSessionFactory,
        security_context: SecurityContext,
    ) -> None:
        self._session_factory = session_factory
        self._security_context = security_context

    def get_machine_status(self, station_id: StationId) -> MachineStatus | None:
        with self._session_factory.session(self._security_context) as session:
            record = session.scalar(
                select(MachineStateRecord)
                .options(joinedload(MachineStateRecord.station))
                .where(MachineStateRecord.station.has(code=station_id.value))
                .order_by(MachineStateRecord.observed_at.desc())
                .limit(1)
            )
        if record is None:
            return None
        return MachineStatus(
            station_id=StationId(record.station.code),
            state=MachineState(record.state),
            active_error_code=record.active_error_code,
            classification=DataClassification(record.classification),
        )


class PostgreSqlDocumentCatalogRepository:
    """Map RLS-filtered ORM document metadata to the Docling boundary DTO."""

    def __init__(
        self,
        session_factory: PostgreSqlSessionFactory,
        security_context: SecurityContext,
    ) -> None:
        self._session_factory = session_factory
        self._security_context = security_context

    def list_documents(self):
        from industrial_ai_agent.infrastructure.docling_ingestion import CatalogDocument

        with self._session_factory.session(self._security_context) as session:
            records = tuple(
                session.scalars(
                    select(DocumentCatalogRecord)
                    .options(joinedload(DocumentCatalogRecord.station))
                    .order_by(DocumentCatalogRecord.file_path)
                )
            )
        return tuple(
            CatalogDocument(
                document_id=record.id,
                title=record.title,
                classification=DataClassification(record.classification),
                mime_type=record.mime_type,
                source_system=record.source_system,
                station_code=record.station.code
                if record.station is not None
                else None,
                version=record.version,
                valid_from=record.valid_from.isoformat(),
                tags=tuple(record.tags),
                file_path=record.file_path,
                checksum=record.checksum,
            )
            for record in records
        )

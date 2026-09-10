"""SQLAlchemy 2.x PostgreSQL adapters with transaction-scoped RLS clearance."""

import hashlib
import re
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path, PurePosixPath, PureWindowsPath
from uuid import uuid4

from sqlalchemy import Connection, Engine, create_engine, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload, sessionmaker

from industrial_ai_agent.application.document_content import (
    AuthorizedDocumentContent,
)
from industrial_ai_agent.domain.factory_discovery import (
    ProductDiscovery,
    ProductOverview,
    StationDiscovery,
    StationOverview,
)
from industrial_ai_agent.domain.machine_status import MachineState, MachineStatus
from industrial_ai_agent.domain.maintenance_ticket import (
    MaintenanceTicket,
    MaintenanceTicketId,
    MaintenanceTicketRequestId,
)
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
    MaintenanceTicketRecord,
    ProductEventRecord,
    ProductRecord,
    StationRecord,
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


class PostgreSqlFactoryDiscoveryRepository:
    """Read bounded discovery projections from RLS-filtered factory records."""

    def __init__(
        self,
        session_factory: PostgreSqlSessionFactory,
        security_context: SecurityContext,
    ) -> None:
        self._session_factory = session_factory
        self._security_context = security_context

    def list_stations(self) -> tuple[StationDiscovery, ...]:
        with self._session_factory.session(self._security_context) as session:
            stations = tuple(
                session.scalars(select(StationRecord).order_by(StationRecord.code))
            )
            return tuple(
                self._station_discovery(session, station) for station in stations
            )

    def get_station_overview(self, station_id: StationId) -> StationOverview | None:
        with self._session_factory.session(self._security_context) as session:
            station = session.scalar(
                select(StationRecord).where(StationRecord.code == station_id.value)
            )
            if station is None:
                return None
            events = tuple(
                session.scalars(
                    select(ProductEventRecord)
                    .join(ProductRecord)
                    .where(ProductEventRecord.station_id == station.id)
                    .order_by(ProductEventRecord.event_at.desc())
                    .limit(20)
                )
            )
            return StationOverview(
                station=self._station_discovery(session, station),
                recent_product_ids=_distinct_product_ids(events),
                recent_products=tuple(
                    self._product_discovery(session, product)
                    for product in _distinct_products(events)
                ),
            )

    def list_products(self) -> tuple[ProductDiscovery, ...]:
        with self._session_factory.session(self._security_context) as session:
            products = tuple(
                session.scalars(
                    select(ProductRecord).order_by(ProductRecord.product_code)
                )
            )
            return tuple(
                self._product_discovery(session, product) for product in products
            )

    def get_product_overview(self, product_id: ProductId) -> ProductOverview | None:
        with self._session_factory.session(self._security_context) as session:
            product = session.scalar(
                select(ProductRecord).where(
                    ProductRecord.product_code == product_id.value
                )
            )
            if product is None:
                return None
            events = self._product_events(session, product)
            return ProductOverview(
                product=self._product_discovery(session, product, events),
                passed_station_ids=tuple(
                    StationId(event.station.code) for event in events
                ),
            )

    def _station_discovery(
        self, session: Session, station: StationRecord
    ) -> StationDiscovery:
        state = session.scalar(
            select(MachineStateRecord)
            .where(MachineStateRecord.station_id == station.id)
            .order_by(MachineStateRecord.observed_at.desc())
            .limit(1)
        )
        classifications = [DataClassification(station.classification)]
        if state is not None:
            classifications.append(DataClassification(state.classification))
        return StationDiscovery(
            station_id=StationId(station.code),
            name=station.name,
            state=MachineState(state.state) if state is not None else None,
            active_error_code=state.active_error_code if state is not None else None,
            classification=max(classifications),
        )

    def _product_discovery(
        self,
        session: Session,
        product: ProductRecord,
        events: tuple[ProductEventRecord, ...] | None = None,
    ) -> ProductDiscovery:
        visible_events = (
            events if events is not None else self._product_events(session, product)
        )
        latest = visible_events[-1] if visible_events else None
        classifications = [DataClassification(product.classification)]
        classifications.extend(
            DataClassification(event.classification) for event in visible_events
        )
        return ProductDiscovery(
            product_id=ProductId(product.product_code),
            latest_station_id=StationId(latest.station.code) if latest else None,
            latest_status=ProductionStepStatus(latest.status) if latest else None,
            latest_error_code=latest.error_code if latest else None,
            classification=max(classifications),
        )

    @staticmethod
    def _product_events(
        session: Session, product: ProductRecord
    ) -> tuple[ProductEventRecord, ...]:
        return tuple(
            session.scalars(
                select(ProductEventRecord)
                .options(joinedload(ProductEventRecord.station))
                .where(ProductEventRecord.product_id == product.id)
                .order_by(ProductEventRecord.event_at)
            )
        )


def _distinct_product_ids(
    events: tuple[ProductEventRecord, ...],
) -> tuple[ProductId, ...]:
    return tuple(
        ProductId(product.product_code) for product in _distinct_products(events)
    )


def _distinct_products(
    events: tuple[ProductEventRecord, ...],
) -> tuple[ProductRecord, ...]:
    products: list[ProductRecord] = []
    seen: set[str] = set()
    for event in events:
        product = event.product
        if product.product_code not in seen:
            seen.add(product.product_code)
            products.append(product)
    return tuple(products)


class PostgreSqlMaintenanceTicketRepository:
    """Create station maintenance tickets with a database-enforced request key."""

    def __init__(
        self,
        session_factory: PostgreSqlSessionFactory,
        security_context: SecurityContext,
    ) -> None:
        self._session_factory = session_factory
        self._security_context = security_context

    def get_maintenance_ticket(
        self, ticket_id: MaintenanceTicketId
    ) -> MaintenanceTicket | None:
        with self._session_factory.session(self._security_context) as session:
            record = session.scalar(
                select(MaintenanceTicketRecord)
                .options(joinedload(MaintenanceTicketRecord.station))
                .where(MaintenanceTicketRecord.ticket_code == ticket_id.value)
            )
        if record is None:
            return None
        return MaintenanceTicket(
            ticket_id=record.ticket_code,
            request_id=MaintenanceTicketRequestId(
                record.request_id or record.ticket_code
            ),
            station_id=StationId(record.station.code),
            summary=record.summary or "Maintenance ticket",
            status=record.status,
            classification=DataClassification(record.classification),
        )

    def create_maintenance_ticket(
        self,
        request_id: MaintenanceTicketRequestId,
        station_id: StationId,
        summary: str,
    ) -> MaintenanceTicket:
        with self._session_factory.session(self._security_context) as session:
            existing = session.scalar(
                select(MaintenanceTicketRecord).where(
                    MaintenanceTicketRecord.request_id == request_id.value
                )
            )
            if existing is not None:
                return MaintenanceTicket(
                    ticket_id=existing.ticket_code,
                    request_id=request_id,
                    station_id=station_id,
                    summary=existing.summary or summary,
                    status=existing.status,
                    classification=DataClassification(existing.classification),
                )
            ticket_code = f"MT-{uuid4().hex[:12].upper()}"
            record = MaintenanceTicketRecord(
                id=uuid4(),
                station_id=session.scalar(
                    select(MachineStateRecord.station_id)
                    .where(MachineStateRecord.station.has(code=station_id.value))
                    .limit(1)
                ),
                ticket_code=ticket_code,
                status="OPEN",
                classification=int(self._security_context.clearance),
                request_id=request_id.value,
                summary=summary,
            )
            if record.station_id is None:
                raise ValueError(f"Unknown station: {station_id.value}")
            try:
                with session.begin_nested():
                    session.add(record)
                    session.flush()
            except IntegrityError:
                # A concurrent resume won the request-id race. Read its ticket inside
                # the still-valid outer transaction and return the idempotent result.
                existing = session.scalar(
                    select(MaintenanceTicketRecord).where(
                        MaintenanceTicketRecord.request_id == request_id.value
                    )
                )
                if existing is None:
                    raise
                return MaintenanceTicket(
                    ticket_id=existing.ticket_code,
                    request_id=request_id,
                    station_id=station_id,
                    summary=existing.summary or summary,
                    status=existing.status,
                    classification=DataClassification(existing.classification),
                )
            return MaintenanceTicket(
                ticket_id=ticket_code,
                request_id=request_id,
                station_id=station_id,
                summary=summary,
                status="OPEN",
                classification=self._security_context.clearance,
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


class PostgreSqlDocumentContentRepository:
    """Serve only RLS-visible, checksum-verified cataloged document bytes."""

    def __init__(
        self, session_factory: PostgreSqlSessionFactory, document_root: Path
    ) -> None:
        self._session_factory = session_factory
        self._document_root = document_root.resolve()

    def get_document(
        self, document_id: str, security_context: SecurityContext
    ) -> AuthorizedDocumentContent | None:
        with self._session_factory.session(security_context) as session:
            record = session.scalar(
                select(DocumentCatalogRecord).where(
                    DocumentCatalogRecord.id == document_id
                )
            )
        if record is None:
            return None
        path = self._catalog_path(record.file_path)
        if path is None:
            return None
        try:
            content = path.read_bytes()
        except OSError:
            return None
        if hashlib.sha256(content).hexdigest() != record.checksum:
            return None
        return AuthorizedDocumentContent(
            content=content,
            media_type=_safe_media_type(record.mime_type),
            filename=_safe_catalog_filename(record.title, path.suffix),
        )

    def _catalog_path(self, file_path: str) -> Path | None:
        relative_path = _document_content_relative_path(file_path)
        if relative_path is None:
            return None
        candidate = (self._document_root / relative_path).resolve()
        if not candidate.is_relative_to(self._document_root) or not candidate.is_file():
            return None
        return candidate


def _document_content_relative_path(file_path: str) -> Path | None:
    """Translate catalog provenance to a safe path below the mounted content root."""
    if not file_path or "\\" in file_path or PureWindowsPath(file_path).is_absolute():
        return None
    path = PurePosixPath(file_path)
    if (
        path.is_absolute()
        or not path.parts
        or path.parts[0] not in {"documents", "images"}
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        return None
    return Path(*path.parts)


def _safe_media_type(value: str) -> str:
    return (
        value
        if re.fullmatch(r"[A-Za-z0-9!#$&^_.+-]+/[A-Za-z0-9!#$&^_.+-]+", value)
        else "application/octet-stream"
    )


def _safe_catalog_filename(title: str, suffix: str) -> str:
    normalized_stem = re.sub(r"[^A-Za-z0-9._-]+", "-", title).strip(".-")[:96]
    normalized_suffix = (
        suffix.lower() if re.fullmatch(r"\.[A-Za-z0-9]{1,10}", suffix) else ""
    )
    return f"{normalized_stem or 'document'}{normalized_suffix}"

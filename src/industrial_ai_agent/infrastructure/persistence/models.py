"""SQLAlchemy 2.x mappings for the classified FACTORY-DEMO-01 persistence model."""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import ClassVar
from uuid import UUID

from sqlalchemy import (
    ARRAY,
    JSON,
    Date,
    DateTime,
    ForeignKey,
    SmallInteger,
    String,
    Text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """Declarative SQLAlchemy base kept entirely in Infrastructure."""


class FactoryRecord(Base):
    __tablename__ = "factory"
    id: Mapped[UUID] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String, unique=True)
    name: Mapped[str] = mapped_column(String)
    classification: Mapped[int] = mapped_column(SmallInteger)
    stations: Mapped[list[StationRecord]] = relationship(back_populates="factory")


class StationRecord(Base):
    __tablename__ = "station"
    id: Mapped[UUID] = mapped_column(primary_key=True)
    factory_id: Mapped[UUID] = mapped_column(ForeignKey("factory.id"))
    code: Mapped[str] = mapped_column(String, unique=True)
    name: Mapped[str] = mapped_column(String)
    classification: Mapped[int] = mapped_column(SmallInteger)
    factory: Mapped[FactoryRecord] = relationship(back_populates="stations")
    product_events: Mapped[list[ProductEventRecord]] = relationship(
        back_populates="station"
    )
    machine_states: Mapped[list[MachineStateRecord]] = relationship(
        back_populates="station"
    )


class ProductRecord(Base):
    __tablename__ = "product"
    id: Mapped[UUID] = mapped_column(primary_key=True)
    factory_id: Mapped[UUID] = mapped_column(ForeignKey("factory.id"))
    product_code: Mapped[str] = mapped_column(String, unique=True)
    classification: Mapped[int] = mapped_column(SmallInteger)
    events: Mapped[list[ProductEventRecord]] = relationship(back_populates="product")


class ProductionOrderRecord(Base):
    __tablename__ = "production_order"
    id: Mapped[UUID] = mapped_column(primary_key=True)
    factory_id: Mapped[UUID] = mapped_column(ForeignKey("factory.id"))
    order_code: Mapped[str] = mapped_column(String, unique=True)
    classification: Mapped[int] = mapped_column(SmallInteger)


class ProductEventRecord(Base):
    __tablename__ = "product_event"
    id: Mapped[UUID] = mapped_column(primary_key=True)
    product_id: Mapped[UUID] = mapped_column(ForeignKey("product.id"))
    station_id: Mapped[UUID] = mapped_column(ForeignKey("station.id"))
    event_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String)
    error_code: Mapped[str | None] = mapped_column(String)
    classification: Mapped[int] = mapped_column(SmallInteger)
    product: Mapped[ProductRecord] = relationship(back_populates="events")
    station: Mapped[StationRecord] = relationship(back_populates="product_events")


class MachineStateRecord(Base):
    __tablename__ = "machine_state"
    id: Mapped[UUID] = mapped_column(primary_key=True)
    station_id: Mapped[UUID] = mapped_column(ForeignKey("station.id"))
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    state: Mapped[str] = mapped_column(String)
    active_error_code: Mapped[str | None] = mapped_column(String)
    classification: Mapped[int] = mapped_column(SmallInteger)
    station: Mapped[StationRecord] = relationship(back_populates="machine_states")


class AlarmEventRecord(Base):
    __tablename__ = "alarm_event"
    id: Mapped[UUID] = mapped_column(primary_key=True)
    station_id: Mapped[UUID] = mapped_column(ForeignKey("station.id"))
    event_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    alarm_code: Mapped[str] = mapped_column(String)
    severity: Mapped[str] = mapped_column(String)
    classification: Mapped[int] = mapped_column(SmallInteger)


class QualityInspectionRecord(Base):
    __tablename__ = "quality_inspection"
    id: Mapped[UUID] = mapped_column(primary_key=True)
    product_id: Mapped[UUID] = mapped_column(ForeignKey("product.id"))
    station_id: Mapped[UUID] = mapped_column(ForeignKey("station.id"))
    inspected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    result: Mapped[str] = mapped_column(String)
    defect_code: Mapped[str | None] = mapped_column(String)
    classification: Mapped[int] = mapped_column(SmallInteger)


class MaintenanceEventRecord(Base):
    __tablename__ = "maintenance_event"
    id: Mapped[UUID] = mapped_column(primary_key=True)
    station_id: Mapped[UUID] = mapped_column(ForeignKey("station.id"))
    event_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    action: Mapped[str] = mapped_column(Text)
    outcome: Mapped[str] = mapped_column(Text)
    classification: Mapped[int] = mapped_column(SmallInteger)


class MaintenanceTicketRecord(Base):
    __tablename__ = "maintenance_ticket"
    id: Mapped[UUID] = mapped_column(primary_key=True)
    station_id: Mapped[UUID] = mapped_column(ForeignKey("station.id"))
    ticket_code: Mapped[str] = mapped_column(String, unique=True)
    status: Mapped[str] = mapped_column(String)
    classification: Mapped[int] = mapped_column(SmallInteger)
    request_id: Mapped[str | None] = mapped_column(String, unique=True)
    summary: Mapped[str | None] = mapped_column(Text)


class ProcessParameterRecord(Base):
    __tablename__ = "process_parameter"
    id: Mapped[UUID] = mapped_column(primary_key=True)
    station_id: Mapped[UUID] = mapped_column(ForeignKey("station.id"))
    parameter_name: Mapped[str] = mapped_column(String)
    parameter_value: Mapped[str] = mapped_column(Text)
    classification: Mapped[int] = mapped_column(SmallInteger)


class DocumentCatalogRecord(Base):
    __tablename__ = "document_catalog"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    title: Mapped[str] = mapped_column(String)
    classification: Mapped[int] = mapped_column(SmallInteger)
    mime_type: Mapped[str] = mapped_column(String)
    source_system: Mapped[str] = mapped_column(String)
    factory_id: Mapped[UUID] = mapped_column(ForeignKey("factory.id"))
    station_id: Mapped[UUID | None] = mapped_column(ForeignKey("station.id"))
    version: Mapped[str] = mapped_column(String)
    valid_from: Mapped[date] = mapped_column(Date)
    tags: Mapped[list[str]] = mapped_column(ARRAY(String))
    file_path: Mapped[str] = mapped_column(String, unique=True)
    checksum: Mapped[str] = mapped_column(String, unique=True)
    station: Mapped[StationRecord | None] = relationship()


class AgentRunRecord(Base):
    """Infrastructure-only mapping for durable API run lifecycle records."""

    __tablename__ = "agent_runs"
    __table_args__: ClassVar[dict[str, str]] = {"schema": "agent_runtime"}

    run_id: Mapped[UUID] = mapped_column(primary_key=True)
    thread_id: Mapped[UUID] = mapped_column(unique=True)
    status: Mapped[str] = mapped_column(String)
    data_classification: Mapped[int] = mapped_column(SmallInteger)
    model_profile: Mapped[str | None] = mapped_column(String)
    request_text: Mapped[str] = mapped_column(Text)
    final_answer: Mapped[str | None] = mapped_column(Text)
    error_code: Mapped[str | None] = mapped_column(String)
    error_message: Mapped[str | None] = mapped_column(Text)
    tool_call_summary: Mapped[list[dict[str, object]]] = mapped_column(JSON)
    approval_payload: Mapped[dict[str, object] | None] = mapped_column(JSON)
    interrupted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default="CURRENT_TIMESTAMP"
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default="CURRENT_TIMESTAMP",
        onupdate=lambda: datetime.now(UTC),
    )

"""Reproducible synthetic FACTORY-DEMO-01 ORM seed and catalog bootstrap."""

import json
import os
from datetime import UTC, date, datetime
from pathlib import Path
from uuid import UUID

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from industrial_ai_agent.infrastructure.persistence.models import (
    AlarmEventRecord,
    DocumentCatalogRecord,
    FactoryRecord,
    MachineStateRecord,
    MaintenanceEventRecord,
    MaintenanceTicketRecord,
    ProcessParameterRecord,
    ProductEventRecord,
    ProductionOrderRecord,
    ProductRecord,
    QualityInspectionRecord,
    StationRecord,
)

DEMO_FACTORY_ROOT = Path(
    os.getenv("DEMO_FACTORY_ROOT", str(Path.cwd() / "demo_factory"))
)
FACTORY_ID = "00000000-0000-0000-0000-000000000001"
STATIONS = {
    "S01": "00000000-0000-0000-0000-000000000101",
    "S02": "00000000-0000-0000-0000-000000000102",
    "S03": "00000000-0000-0000-0000-000000000103",
    "S04": "00000000-0000-0000-0000-000000000104",
    "S05": "00000000-0000-0000-0000-000000000105",
}
PRODUCTS = {
    "P4711": "00000000-0000-0000-0000-000000004711",
    "P4801": "00000000-0000-0000-0000-000000004801",
    "P4802": "00000000-0000-0000-0000-000000004802",
    "P4805": "00000000-0000-0000-0000-000000004805",
    "P4811": "00000000-0000-0000-0000-000000004811",
}


def seed_demo_data(admin_database_url: str) -> None:
    """Upsert the deterministic synthetic scenario through SQLAlchemy mappings."""
    engine = create_engine(admin_database_url, pool_pre_ping=True)
    try:
        with Session(engine) as session, session.begin():
            _seed_factory(session)
            _seed_product_events(session)
            _seed_operational_records(session)
            _seed_document_catalog(session)
    finally:
        engine.dispose()


def _seed_factory(session: Session) -> None:
    session.merge(
        FactoryRecord(
            id=_uuid(FACTORY_ID),
            code="FACTORY-DEMO-01",
            name="Synthetic Demonstration Factory",
            classification=0,
        )
    )
    for code, name in (
        ("S01", "Material Intake"),
        ("S02", "Positioning"),
        ("S03", "Robot Assembly"),
        ("S04", "Quality Inspection"),
        ("S05", "Packaging"),
    ):
        session.merge(
            StationRecord(
                id=_uuid(STATIONS[code]),
                factory_id=_uuid(FACTORY_ID),
                code=code,
                name=name,
                classification=0,
            )
        )
    for code, identifier in PRODUCTS.items():
        session.merge(
            ProductRecord(
                id=_uuid(identifier),
                factory_id=_uuid(FACTORY_ID),
                product_code=code,
                classification=2,
            )
        )


def _seed_product_events(session: Session) -> None:
    events = (
        ("P4711", "S01", "2026-01-15T08:00:00+00:00", "COMPLETED", None),
        ("P4711", "S02", "2026-01-15T08:04:00+00:00", "WARNING", "POSITION-ENC-02"),
        ("P4711", "S03", "2026-01-15T08:07:00+00:00", "COMPLETED", None),
        ("P4711", "S04", "2026-01-15T08:09:00+00:00", "FAILED", "QUALITY-09"),
        ("P4801", "S02", "2026-01-16T08:00:00+00:00", "WARNING", "POSITION-ENC-02"),
        ("P4802", "S02", "2026-01-16T08:11:00+00:00", "WARNING", "POSITION-ENC-02"),
        ("P4805", "S02", "2026-01-16T08:22:00+00:00", "WARNING", "POSITION-ENC-02"),
        ("P4811", "S02", "2026-01-16T08:33:00+00:00", "WARNING", "POSITION-ENC-02"),
    )
    for index, (product_code, station_code, event_at, status, error_code) in enumerate(
        events, start=1
    ):
        session.merge(
            ProductEventRecord(
                id=_uuid(f"00000000-0000-0000-0000-{index:012d}"),
                product_id=_uuid(PRODUCTS[product_code]),
                station_id=_uuid(STATIONS[station_code]),
                event_at=datetime.fromisoformat(event_at),
                status=status,
                error_code=error_code,
                classification=2,
            )
        )


def _seed_operational_records(session: Session) -> None:
    session.merge(
        ProductionOrderRecord(
            id=_uuid("00000000-0000-0000-0000-000000000501"),
            factory_id=_uuid(FACTORY_ID),
            order_code="PO-P4711",
            classification=2,
        )
    )
    for index, (station, observed_at, state, error_code) in enumerate(
        (
            ("S02", "2026-01-16T09:00:00+00:00", "FAULTED", "POSITION-ENC-02"),
            ("S04", "2026-01-15T08:10:00+00:00", "FAULTED", "QUALITY-09"),
        ),
        start=201,
    ):
        session.merge(
            MachineStateRecord(
                id=_uuid(f"00000000-0000-0000-0000-{index:012d}"),
                station_id=_uuid(STATIONS[station]),
                observed_at=datetime.fromisoformat(observed_at),
                state=state,
                active_error_code=error_code,
                classification=2,
            )
        )
    session.merge(
        AlarmEventRecord(
            id=_uuid("00000000-0000-0000-0000-000000000601"),
            station_id=_uuid(STATIONS["S02"]),
            event_at=datetime(2026, 1, 16, 8, 35, tzinfo=UTC),
            alarm_code="E-STOP-17",
            severity="high",
            classification=2,
        )
    )
    session.merge(
        QualityInspectionRecord(
            id=_uuid("00000000-0000-0000-0000-000000000701"),
            product_id=_uuid(PRODUCTS["P4711"]),
            station_id=_uuid(STATIONS["S04"]),
            inspected_at=datetime(2026, 1, 15, 8, 9, tzinfo=UTC),
            result="REJECTED",
            defect_code="QUALITY-09",
            classification=2,
        )
    )
    for index, action in enumerate(
        (
            "encoder replacement",
            "homing",
            "dry cycle",
            "inspection verification",
            "return to service",
        ),
        start=301,
    ):
        session.merge(
            MaintenanceEventRecord(
                id=_uuid(f"00000000-0000-0000-0000-{index:012d}"),
                station_id=_uuid(STATIONS["S02"]),
                event_at=datetime(2026, 1, 17, 9, index - 300, tzinfo=UTC),
                action=action,
                outcome="completed",
                classification=2,
            )
        )
    session.merge(
        MaintenanceTicketRecord(
            id=_uuid("00000000-0000-0000-0000-000000000801"),
            station_id=_uuid(STATIONS["S02"]),
            ticket_code="MT-S02-20260117",
            status="CLOSED",
            classification=2,
        )
    )
    session.merge(
        ProcessParameterRecord(
            id=_uuid("00000000-0000-0000-0000-000000000401"),
            station_id=_uuid(STATIONS["S03"]),
            parameter_name="robot_trajectory_limit",
            parameter_value="12.5 mm/s",
            classification=3,
        )
    )


def _seed_document_catalog(session: Session) -> None:
    catalog = json.loads(
        (DEMO_FACTORY_ROOT / "metadata" / "document_catalog.json").read_text(
            encoding="utf-8"
        )
    )
    for document in catalog:
        session.merge(
            DocumentCatalogRecord(
                id=document["document_id"],
                title=document["title"],
                classification={
                    "PUBLIC": 0,
                    "INTERNAL": 1,
                    "CONFIDENTIAL": 2,
                    "RESTRICTED": 3,
                }[document["classification"]],
                mime_type=document["mime_type"],
                source_system=document["source_system"],
                factory_id=_uuid(FACTORY_ID),
                station_id=_uuid(STATIONS[document["station_code"]])
                if document["station_code"]
                else None,
                version=document["version"],
                valid_from=date.fromisoformat(document["valid_from"]),
                tags=list(document["tags"]),
                file_path=document["file_path"],
                checksum=document["checksum"],
            )
        )


def _uuid(value: str) -> UUID:
    return UUID(value)

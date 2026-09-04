"""Reproducible synthetic FACTORY-DEMO-01 seed data and document catalog loading."""

import json
import os
from datetime import UTC, date, datetime
from pathlib import Path

from sqlalchemy import create_engine, text

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
    """Idempotently insert synthetic records after the Alembic schema migration."""
    engine = create_engine(admin_database_url, pool_pre_ping=True)
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO factory (id, code, name, classification)
                VALUES (:id, 'FACTORY-DEMO-01', 'Synthetic Demonstration Factory', 0)
                ON CONFLICT (id) DO NOTHING
                """
            ),
            {"id": FACTORY_ID},
        )
        for code, name in (
            ("S01", "Material Intake"),
            ("S02", "Positioning"),
            ("S03", "Robot Assembly"),
            ("S04", "Quality Inspection"),
            ("S05", "Packaging"),
        ):
            connection.execute(
                text(
                    """
                    INSERT INTO station (id, factory_id, code, name, classification)
                    VALUES (:id, :factory_id, :code, :name, 0)
                    ON CONFLICT (id) DO NOTHING
                    """
                ),
                {
                    "id": STATIONS[code],
                    "factory_id": FACTORY_ID,
                    "code": code,
                    "name": name,
                },
            )
        for code, identifier in PRODUCTS.items():
            connection.execute(
                text(
                    """
                    INSERT INTO product (id, factory_id, product_code, classification)
                    VALUES (:id, :factory_id, :product_code, 2)
                    ON CONFLICT (id) DO NOTHING
                    """
                ),
                {"id": identifier, "factory_id": FACTORY_ID, "product_code": code},
            )
        _seed_product_events(connection)
        _seed_operational_records(connection)
        _seed_document_catalog(connection)
    engine.dispose()


def _seed_product_events(connection) -> None:
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
        connection.execute(
            text(
                """
                INSERT INTO product_event
                    (id, product_id, station_id, event_at, status, error_code, classification)
                VALUES (:id, :product_id, :station_id, :event_at, :status, :error_code, 2)
                ON CONFLICT (id) DO NOTHING
                """
            ),
            {
                "id": f"00000000-0000-0000-0000-{index:012d}",
                "product_id": PRODUCTS[product_code],
                "station_id": STATIONS[station_code],
                "event_at": datetime.fromisoformat(event_at),
                "status": status,
                "error_code": error_code,
            },
        )


def _seed_operational_records(connection) -> None:
    connection.execute(
        text(
            """
            INSERT INTO production_order (id, factory_id, order_code, classification)
            VALUES ('00000000-0000-0000-0000-000000000501', :factory_id, 'PO-P4711', 2)
            ON CONFLICT (id) DO NOTHING
            """
        ),
        {"factory_id": FACTORY_ID},
    )
    records = (
        (
            "machine_state",
            "00000000-0000-0000-0000-000000000201",
            "S02",
            "2026-01-16T09:00:00+00:00",
            "FAULTED",
            "POSITION-ENC-02",
        ),
        (
            "machine_state",
            "00000000-0000-0000-0000-000000000202",
            "S04",
            "2026-01-15T08:10:00+00:00",
            "FAULTED",
            "QUALITY-09",
        ),
    )
    for table, identifier, station_code, observed_at, state, error_code in records:
        connection.execute(
            text(
                f"""
                INSERT INTO {table} (id, station_id, observed_at, state, active_error_code, classification)
                VALUES (:id, :station_id, :observed_at, :state, :error_code, 2)
                ON CONFLICT (id) DO NOTHING
                """
            ),
            {
                "id": identifier,
                "station_id": STATIONS[station_code],
                "observed_at": datetime.fromisoformat(observed_at),
                "state": state,
                "error_code": error_code,
            },
        )
    connection.execute(
        text(
            """
            INSERT INTO alarm_event
                (id, station_id, event_at, alarm_code, severity, classification)
            VALUES ('00000000-0000-0000-0000-000000000601', :station_id,
                    '2026-01-16T08:35:00+00:00', 'E-STOP-17', 'high', 2)
            ON CONFLICT (id) DO NOTHING
            """
        ),
        {"station_id": STATIONS["S02"]},
    )
    connection.execute(
        text(
            """
            INSERT INTO quality_inspection
                (id, product_id, station_id, inspected_at, result, defect_code, classification)
            VALUES ('00000000-0000-0000-0000-000000000701', :product_id, :station_id,
                    '2026-01-15T08:09:00+00:00', 'REJECTED', 'QUALITY-09', 2)
            ON CONFLICT (id) DO NOTHING
            """
        ),
        {"product_id": PRODUCTS["P4711"], "station_id": STATIONS["S04"]},
    )
    for index, action in enumerate(
        (
            "encoder replacement",
            "homing",
            "dry cycle",
            "inspection verification",
            "return to service",
        ),
        start=1,
    ):
        connection.execute(
            text(
                """
                INSERT INTO maintenance_event (id, station_id, event_at, action, outcome, classification)
                VALUES (:id, :station_id, :event_at, :action, 'completed', 2)
                ON CONFLICT (id) DO NOTHING
                """
            ),
            {
                "id": f"00000000-0000-0000-0000-{300 + index:012d}",
                "station_id": STATIONS["S02"],
                "event_at": datetime(2026, 1, 17, 9, index, tzinfo=UTC),
                "action": action,
            },
        )
    connection.execute(
        text(
            """
            INSERT INTO maintenance_ticket
                (id, station_id, ticket_code, status, classification)
            VALUES ('00000000-0000-0000-0000-000000000801', :station_id,
                    'MT-S02-20260117', 'CLOSED', 2)
            ON CONFLICT (id) DO NOTHING
            """
        ),
        {"station_id": STATIONS["S02"]},
    )
    for index, (name, value) in enumerate(
        (("robot_trajectory_limit", "12.5 mm/s"),), start=1
    ):
        connection.execute(
            text(
                """
                INSERT INTO process_parameter (id, station_id, parameter_name, parameter_value, classification)
                VALUES (:id, :station_id, :parameter_name, :parameter_value, 3)
                ON CONFLICT (id) DO NOTHING
                """
            ),
            {
                "id": f"00000000-0000-0000-0000-{400 + index:012d}",
                "station_id": STATIONS["S03"],
                "parameter_name": name,
                "parameter_value": value,
            },
        )


def _seed_document_catalog(connection) -> None:
    catalog = json.loads(
        (DEMO_FACTORY_ROOT / "metadata" / "document_catalog.json").read_text(
            encoding="utf-8"
        )
    )
    for document in catalog:
        station_code = document["station_code"]
        connection.execute(
            text(
                """
                INSERT INTO document_catalog
                    (id, title, classification, mime_type, source_system, factory_id,
                     station_id, version, valid_from, tags, file_path, checksum)
                VALUES (:id, :title, :classification, :mime_type, :source_system, :factory_id,
                        :station_id, :version, :valid_from, :tags, :file_path, :checksum)
                ON CONFLICT (id) DO UPDATE SET checksum = EXCLUDED.checksum,
                    updated_at = CURRENT_TIMESTAMP
                """
            ),
            {
                "id": document["document_id"],
                "title": document["title"],
                "classification": {
                    "PUBLIC": 0,
                    "INTERNAL": 1,
                    "CONFIDENTIAL": 2,
                    "RESTRICTED": 3,
                }[document["classification"]],
                "mime_type": document["mime_type"],
                "source_system": document["source_system"],
                "factory_id": FACTORY_ID,
                "station_id": STATIONS.get(station_code),
                "version": document["version"],
                "valid_from": date.fromisoformat(document["valid_from"]),
                "tags": document["tags"],
                "file_path": document["file_path"],
                "checksum": document["checksum"],
            },
        )

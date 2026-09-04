"""Create classified persistent factory and document catalog schema."""

from alembic import op

revision = "0001_factory_data"
down_revision = None
branch_labels = None
depends_on = None

_TABLES = (
    "factory",
    "station",
    "product",
    "production_order",
    "product_event",
    "machine_state",
    "alarm_event",
    "quality_inspection",
    "maintenance_event",
    "maintenance_ticket",
    "process_parameter",
    "document_catalog",
)


def upgrade() -> None:
    op.execute("SET ROLE factory_migration_owner")
    op.execute(
        """
        CREATE TABLE factory (
            id UUID PRIMARY KEY,
            code TEXT NOT NULL UNIQUE,
            name TEXT NOT NULL,
            classification SMALLINT NOT NULL CHECK (classification BETWEEN 0 AND 3),
            created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE station (
            id UUID PRIMARY KEY,
            factory_id UUID NOT NULL REFERENCES factory(id),
            code TEXT NOT NULL UNIQUE,
            name TEXT NOT NULL,
            classification SMALLINT NOT NULL CHECK (classification BETWEEN 0 AND 3),
            created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE product (
            id UUID PRIMARY KEY,
            factory_id UUID NOT NULL REFERENCES factory(id),
            product_code TEXT NOT NULL UNIQUE,
            classification SMALLINT NOT NULL CHECK (classification BETWEEN 0 AND 3),
            created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE production_order (
            id UUID PRIMARY KEY,
            factory_id UUID NOT NULL REFERENCES factory(id),
            order_code TEXT NOT NULL UNIQUE,
            classification SMALLINT NOT NULL CHECK (classification BETWEEN 0 AND 3),
            created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE product_event (
            id UUID PRIMARY KEY,
            product_id UUID NOT NULL REFERENCES product(id),
            station_id UUID NOT NULL REFERENCES station(id),
            event_at TIMESTAMPTZ NOT NULL,
            status TEXT NOT NULL CHECK (status IN ('COMPLETED', 'FAILED', 'WARNING')),
            error_code TEXT,
            classification SMALLINT NOT NULL CHECK (classification BETWEEN 0 AND 3),
            created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX product_event_product_time_idx ON product_event(product_id, event_at);
        CREATE INDEX product_event_station_time_idx ON product_event(station_id, event_at);
        CREATE TABLE machine_state (
            id UUID PRIMARY KEY,
            station_id UUID NOT NULL REFERENCES station(id),
            observed_at TIMESTAMPTZ NOT NULL,
            state TEXT NOT NULL CHECK (state IN ('RUNNING', 'STOPPED', 'FAULTED', 'MAINTENANCE')),
            active_error_code TEXT,
            classification SMALLINT NOT NULL CHECK (classification BETWEEN 0 AND 3),
            created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX machine_state_station_time_idx ON machine_state(station_id, observed_at DESC);
        CREATE TABLE alarm_event (
            id UUID PRIMARY KEY,
            station_id UUID NOT NULL REFERENCES station(id),
            event_at TIMESTAMPTZ NOT NULL,
            alarm_code TEXT NOT NULL,
            severity TEXT NOT NULL,
            classification SMALLINT NOT NULL CHECK (classification BETWEEN 0 AND 3),
            created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE quality_inspection (
            id UUID PRIMARY KEY,
            product_id UUID NOT NULL REFERENCES product(id),
            station_id UUID NOT NULL REFERENCES station(id),
            inspected_at TIMESTAMPTZ NOT NULL,
            result TEXT NOT NULL CHECK (result IN ('ACCEPTED', 'REJECTED')),
            defect_code TEXT,
            classification SMALLINT NOT NULL CHECK (classification BETWEEN 0 AND 3),
            created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE maintenance_event (
            id UUID PRIMARY KEY,
            station_id UUID NOT NULL REFERENCES station(id),
            event_at TIMESTAMPTZ NOT NULL,
            action TEXT NOT NULL,
            outcome TEXT NOT NULL,
            classification SMALLINT NOT NULL CHECK (classification BETWEEN 0 AND 3),
            created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE maintenance_ticket (
            id UUID PRIMARY KEY,
            station_id UUID NOT NULL REFERENCES station(id),
            ticket_code TEXT NOT NULL UNIQUE,
            status TEXT NOT NULL,
            classification SMALLINT NOT NULL CHECK (classification BETWEEN 0 AND 3),
            created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE process_parameter (
            id UUID PRIMARY KEY,
            station_id UUID NOT NULL REFERENCES station(id),
            parameter_name TEXT NOT NULL,
            parameter_value TEXT NOT NULL,
            classification SMALLINT NOT NULL CHECK (classification BETWEEN 0 AND 3),
            created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE document_catalog (
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            classification SMALLINT NOT NULL CHECK (classification BETWEEN 0 AND 3),
            mime_type TEXT NOT NULL,
            source_system TEXT NOT NULL,
            factory_id UUID NOT NULL REFERENCES factory(id),
            station_id UUID REFERENCES station(id),
            version TEXT NOT NULL,
            valid_from DATE NOT NULL,
            tags TEXT[] NOT NULL,
            file_path TEXT NOT NULL UNIQUE,
            checksum TEXT NOT NULL UNIQUE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX document_catalog_classification_idx ON document_catalog(classification);
        """
    )
    for table in _TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"""
            CREATE POLICY {table}_clearance_policy ON {table}
            FOR SELECT TO factory_app
            USING (
                classification <= COALESCE(
                    NULLIF(current_setting('app.clearance', true), '')::SMALLINT,
                    -1
                )
            )
            """
        )
        op.execute(f"GRANT SELECT ON {table} TO factory_app")
    op.execute("RESET ROLE")


def downgrade() -> None:
    op.execute("SET ROLE factory_migration_owner")
    for table in reversed(_TABLES):
        op.execute(f"DROP TABLE {table}")
    op.execute("RESET ROLE")

"""Persist maintenance-ticket request idempotency data."""

from alembic import op

revision = "0003_persistent_maintenance_ticket"
down_revision = "0002_agent_runtime"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE alembic_version
            ALTER COLUMN version_num TYPE VARCHAR(64);
        """
    )
    op.execute("SET ROLE factory_migration_owner")
    op.execute(
        """
        ALTER TABLE maintenance_ticket ADD COLUMN request_id TEXT;
        ALTER TABLE maintenance_ticket ADD COLUMN summary TEXT;
        CREATE UNIQUE INDEX maintenance_ticket_request_id_key
            ON maintenance_ticket(request_id) WHERE request_id IS NOT NULL;
        GRANT SELECT, INSERT, UPDATE ON maintenance_ticket TO factory_app;
        """
    )
    op.execute("RESET ROLE")


def downgrade() -> None:
    op.execute("SET ROLE factory_migration_owner")
    op.execute("DROP INDEX maintenance_ticket_request_id_key")
    op.execute("ALTER TABLE maintenance_ticket DROP COLUMN summary")
    op.execute("ALTER TABLE maintenance_ticket DROP COLUMN request_id")
    op.execute("RESET ROLE")

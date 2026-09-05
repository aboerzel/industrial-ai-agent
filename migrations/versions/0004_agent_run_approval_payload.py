"""Persist public approval payloads with agent run lifecycle records."""

from alembic import op

revision = "0004_agent_run_approval_payload"
down_revision = "0003_persistent_maintenance_ticket"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("SET ROLE factory_migration_owner")
    op.execute("ALTER TABLE agent_runtime.agent_runs ADD COLUMN approval_payload JSONB")
    op.execute("RESET ROLE")


def downgrade() -> None:
    op.execute("SET ROLE factory_migration_owner")
    op.execute("ALTER TABLE agent_runtime.agent_runs DROP COLUMN approval_payload")
    op.execute("RESET ROLE")

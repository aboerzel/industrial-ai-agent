"""Persist bounded structured identifier and document references per run."""

from alembic import op

revision = "0014_agent_run_references"
down_revision = "0013_agent_run_investigation_steps"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("SET ROLE factory_migration_owner")
    op.execute(
        """
        ALTER TABLE agent_runtime.agent_runs
            ADD COLUMN identifiers JSONB NOT NULL DEFAULT '[]'::jsonb,
            ADD COLUMN documents JSONB NOT NULL DEFAULT '[]'::jsonb;
        """
    )
    op.execute("RESET ROLE")


def downgrade() -> None:
    op.execute("SET ROLE factory_migration_owner")
    op.execute(
        "ALTER TABLE agent_runtime.agent_runs "
        "DROP COLUMN documents, DROP COLUMN identifiers"
    )
    op.execute("RESET ROLE")

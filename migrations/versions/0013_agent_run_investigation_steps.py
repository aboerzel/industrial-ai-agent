"""Persist bounded structured summaries of completed investigation steps."""

from alembic import op

revision = "0013_agent_run_investigation_steps"
down_revision = "0012_agent_run_next_steps"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("SET ROLE factory_migration_owner")
    op.execute(
        """
        ALTER TABLE agent_runtime.agent_runs
            ADD COLUMN investigation_steps JSONB NOT NULL DEFAULT '[]'::jsonb;
        """
    )
    op.execute("RESET ROLE")


def downgrade() -> None:
    op.execute("SET ROLE factory_migration_owner")
    op.execute("ALTER TABLE agent_runtime.agent_runs DROP COLUMN investigation_steps")
    op.execute("RESET ROLE")

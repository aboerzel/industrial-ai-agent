"""Persist bounded structured follow-up prompts with the agent run."""

from alembic import op

revision = "0012_agent_run_next_steps"
down_revision = "0011_agent_run_investigation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("SET ROLE factory_migration_owner")
    op.execute(
        """
        ALTER TABLE agent_runtime.agent_runs
            ADD COLUMN next_steps JSONB NOT NULL DEFAULT '[]'::jsonb;
        """
    )
    op.execute("RESET ROLE")


def downgrade() -> None:
    op.execute("SET ROLE factory_migration_owner")
    op.execute("ALTER TABLE agent_runtime.agent_runs DROP COLUMN next_steps")
    op.execute("RESET ROLE")

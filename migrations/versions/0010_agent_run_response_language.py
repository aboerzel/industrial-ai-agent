"""Persist the response language selected from the original run request."""

from alembic import op

revision = "0010_agent_run_response_language"
down_revision = "0009_expand_agent_run_profiles"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("SET ROLE factory_migration_owner")
    op.execute(
        """
        ALTER TABLE agent_runtime.agent_runs
            ADD COLUMN response_language TEXT NOT NULL DEFAULT 'EN'
            CHECK (response_language IN ('DE', 'EN'));
        """
    )
    op.execute("RESET ROLE")


def downgrade() -> None:
    op.execute("SET ROLE factory_migration_owner")
    op.execute("ALTER TABLE agent_runtime.agent_runs DROP COLUMN response_language")
    op.execute("RESET ROLE")

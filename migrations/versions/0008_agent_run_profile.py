"""Bind durable agent runs to their server-resolved run profile."""

from alembic import op

revision = "0008_agent_run_profile"
down_revision = "0007_agent_run_approval_audit"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("SET ROLE factory_migration_owner")
    op.execute(
        """
        ALTER TABLE agent_runtime.agent_runs
            ADD COLUMN run_profile TEXT NOT NULL
            DEFAULT 'CONFIDENTIAL_TROUBLESHOOTING'
            CHECK (run_profile IN (
                'INTERNAL_DIAGNOSTIC',
                'CONFIDENTIAL_TROUBLESHOOTING'
            ));
        """
    )
    op.execute("RESET ROLE")


def downgrade() -> None:
    op.execute("SET ROLE factory_migration_owner")
    op.execute("ALTER TABLE agent_runtime.agent_runs DROP COLUMN run_profile")
    op.execute("RESET ROLE")

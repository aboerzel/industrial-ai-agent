"""Persist the full closed set of server-resolved demo run profiles."""

from alembic import op

revision = "0009_expand_agent_run_profiles"
down_revision = "0008_agent_run_profile"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("SET ROLE factory_migration_owner")
    op.execute(
        """
        ALTER TABLE agent_runtime.agent_runs
            DROP CONSTRAINT agent_runs_run_profile_check,
            ADD CONSTRAINT agent_runs_run_profile_check
                CHECK (run_profile IN (
                    'PUBLIC_INFORMATION',
                    'INTERNAL_DIAGNOSTIC',
                    'CONFIDENTIAL_TROUBLESHOOTING',
                    'RESTRICTED_TROUBLESHOOTING'
                ));
        """
    )
    op.execute("RESET ROLE")


def downgrade() -> None:
    op.execute("SET ROLE factory_migration_owner")
    op.execute(
        """
        ALTER TABLE agent_runtime.agent_runs
            DROP CONSTRAINT agent_runs_run_profile_check,
            ADD CONSTRAINT agent_runs_run_profile_check
                CHECK (run_profile IN (
                    'INTERNAL_DIAGNOSTIC',
                    'CONFIDENTIAL_TROUBLESHOOTING'
                ));
        """
    )
    op.execute("RESET ROLE")

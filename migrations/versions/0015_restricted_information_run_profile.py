"""Persist the bounded restricted information run profile."""

from alembic import op

revision = "0015_restricted_information_run_profile"
down_revision = "0014_agent_run_references"
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
                    'RESTRICTED_INFORMATION',
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
                    'PUBLIC_INFORMATION',
                    'INTERNAL_DIAGNOSTIC',
                    'CONFIDENTIAL_TROUBLESHOOTING',
                    'RESTRICTED_TROUBLESHOOTING'
                ));
        """
    )
    op.execute("RESET ROLE")

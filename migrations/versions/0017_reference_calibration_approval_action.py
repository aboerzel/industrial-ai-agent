"""Persist the bounded reference-calibration approval action."""

from alembic import op

revision = "0017_reference_calibration_approval_action"
down_revision = "0016_confidential_recovery_run_profile"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("SET ROLE factory_migration_owner")
    op.execute(
        """
        ALTER TABLE agent_runtime.agent_runs
            DROP CONSTRAINT agent_runs_approval_action_check,
            ADD CONSTRAINT agent_runs_approval_action_check
                CHECK (
                    approval_action IS NULL
                    OR approval_action IN (
                        'create_maintenance_ticket',
                        'execute_reference_calibration'
                    )
                );
        """
    )
    op.execute("RESET ROLE")


def downgrade() -> None:
    op.execute("SET ROLE factory_migration_owner")
    op.execute(
        """
        ALTER TABLE agent_runtime.agent_runs
            DROP CONSTRAINT agent_runs_approval_action_check,
            ADD CONSTRAINT agent_runs_approval_action_check
                CHECK (
                    approval_action IS NULL
                    OR approval_action = 'create_maintenance_ticket'
                );
        """
    )
    op.execute("RESET ROLE")

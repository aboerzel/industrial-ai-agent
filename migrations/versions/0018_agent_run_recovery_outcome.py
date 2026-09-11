"""Persist bounded closed-loop recovery outcomes."""

from alembic import op

revision = "0018_agent_run_recovery_outcome"
down_revision = "0017_reference_calibration_approval_action"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("SET ROLE factory_migration_owner")
    op.execute(
        """
        ALTER TABLE agent_runtime.agent_runs
            ADD COLUMN recovery_outcome VARCHAR,
            ADD CONSTRAINT agent_runs_recovery_outcome_check
                CHECK (
                    recovery_outcome IS NULL
                    OR recovery_outcome IN ('SUCCEEDED', 'NOT_REQUIRED', 'FAILED', 'BLOCKED')
                );
        """
    )
    op.execute("RESET ROLE")


def downgrade() -> None:
    op.execute("SET ROLE factory_migration_owner")
    op.execute(
        """
        ALTER TABLE agent_runtime.agent_runs
            DROP CONSTRAINT agent_runs_recovery_outcome_check,
            DROP COLUMN recovery_outcome;
        """
    )
    op.execute("RESET ROLE")

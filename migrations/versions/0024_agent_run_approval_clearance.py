"""Persist the server-resolved clearance that made a demo approval eligible."""

from alembic import op

revision = "0024_agent_run_approval_clearance"
down_revision = "0023_remove_incompatible_vision_default"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("SET ROLE factory_migration_owner")
    op.execute(
        """
        ALTER TABLE agent_runtime.agent_runs
            ADD COLUMN approval_decided_clearance TEXT,
            ADD CONSTRAINT agent_runs_approval_decided_clearance_check
                CHECK (
                    approval_decided_clearance IS NULL
                    OR approval_decided_clearance IN (
                        'PUBLIC', 'INTERNAL', 'CONFIDENTIAL', 'RESTRICTED'
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
            DROP CONSTRAINT agent_runs_approval_decided_clearance_check,
            DROP COLUMN approval_decided_clearance;
        """
    )
    op.execute("RESET ROLE")

"""Persist safe approval audit facts for runtime read-only inspection."""

from alembic import op

revision = "0007_agent_run_approval_audit"
down_revision = "0006_maintenance_ticket_insert_policy"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("SET ROLE factory_migration_owner")
    op.execute(
        """
        ALTER TABLE agent_runtime.agent_runs
            ADD COLUMN approval_action TEXT,
            ADD COLUMN approval_decision TEXT,
            ADD COLUMN approval_requested_at TIMESTAMPTZ,
            ADD COLUMN approval_decided_at TIMESTAMPTZ,
            ADD CONSTRAINT agent_runs_approval_action_check
                CHECK (approval_action IS NULL OR approval_action = 'create_maintenance_ticket'),
            ADD CONSTRAINT agent_runs_approval_decision_check
                CHECK (approval_decision IS NULL OR approval_decision IN ('approve', 'reject'));
        """
    )
    op.execute("RESET ROLE")


def downgrade() -> None:
    op.execute("SET ROLE factory_migration_owner")
    op.execute(
        """
        ALTER TABLE agent_runtime.agent_runs
            DROP CONSTRAINT agent_runs_approval_decision_check,
            DROP CONSTRAINT agent_runs_approval_action_check,
            DROP COLUMN approval_decided_at,
            DROP COLUMN approval_requested_at,
            DROP COLUMN approval_decision,
            DROP COLUMN approval_action;
        """
    )
    op.execute("RESET ROLE")

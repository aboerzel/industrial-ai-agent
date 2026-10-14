"""Persist authoritative approval generations without authorizing legacy approvals."""

from alembic import op

revision = "0025_approval_generation_identity"
down_revision = "0024_agent_run_approval_clearance"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("SET ROLE factory_migration_owner")
    op.execute(
        """
        ALTER TABLE agent_runtime.agent_runs
            ADD COLUMN approval_generations JSON NOT NULL DEFAULT '{}'::json,
            ADD CONSTRAINT agent_runs_approval_generations_object_check
                CHECK (json_typeof(approval_generations) = 'object');
        """
    )
    op.execute("RESET ROLE")


def downgrade() -> None:
    raise RuntimeError("Approval-generation identity migration is forward-only")

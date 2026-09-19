"""Add explicit manual and automatic model-selection configuration."""

from alembic import op

revision = "0020_model_selection_modes"
down_revision = "0019_model_assignments"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("SET ROLE factory_migration_owner")
    op.execute(
        """
        ALTER TABLE agent_runtime.model_assignments
            ALTER COLUMN model_id DROP NOT NULL,
            ADD COLUMN selection_mode TEXT NOT NULL DEFAULT 'MANUAL',
            ADD COLUMN selection_policy TEXT,
            ADD CONSTRAINT model_assignments_selection_mode_check
                CHECK (selection_mode IN ('MANUAL', 'AUTO')),
            ADD CONSTRAINT model_assignments_selection_policy_check
                CHECK (selection_policy IS NULL OR selection_policy IN ('QUALITY_FIRST', 'COST_FIRST')),
            ADD CONSTRAINT model_assignments_selection_shape_check
                CHECK (
                    (selection_mode = 'MANUAL' AND model_id IS NOT NULL AND selection_policy IS NULL)
                    OR
                    (selection_mode = 'AUTO' AND model_id IS NULL AND selection_policy IS NOT NULL)
                );
        """
    )
    op.execute("RESET ROLE")


def downgrade() -> None:
    op.execute("SET ROLE factory_migration_owner")
    op.execute(
        """
        DELETE FROM agent_runtime.model_assignments WHERE selection_mode = 'AUTO';
        ALTER TABLE agent_runtime.model_assignments
            DROP CONSTRAINT model_assignments_selection_shape_check,
            DROP CONSTRAINT model_assignments_selection_policy_check,
            DROP CONSTRAINT model_assignments_selection_mode_check,
            DROP COLUMN selection_policy,
            DROP COLUMN selection_mode,
            ALTER COLUMN model_id SET NOT NULL;
        """
    )
    op.execute("RESET ROLE")

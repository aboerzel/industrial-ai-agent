"""Remove an incompatible legacy vision model assignment."""

from alembic import op

revision = "0023_remove_incompatible_vision_default"
down_revision = "0022_normalize_local_model_assignment_defaults"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("SET ROLE factory_migration_owner")
    op.execute(
        """
        DELETE FROM agent_runtime.model_assignments
        WHERE consumer_id = 'vision.vlm'
          AND model_id = 'local_quality'
        """
    )
    op.execute("RESET ROLE")


def downgrade() -> None:
    pass

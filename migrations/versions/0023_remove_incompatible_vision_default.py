"""Preserve existing vision assignments during upgrade."""

from alembic import op

revision = "0023_remove_incompatible_vision_default"
down_revision = "0022_normalize_local_model_assignment_defaults"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Do not infer assignment provenance from consumer or model values.

    At this revision, ``updated_by`` is informational only.  A matching
    ``vision.vlm/local_quality`` row may be an explicit historical operator choice,
    so capability validation must reject it at execution time instead of deleting it.
    """
    op.execute("SET ROLE factory_migration_owner")
    op.execute("RESET ROLE")


def downgrade() -> None:
    pass

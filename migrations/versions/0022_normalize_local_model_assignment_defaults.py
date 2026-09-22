"""Add missing local default model assignments without rewriting configuration."""

from alembic import op

revision = "0022_normalize_local_model_assignment_defaults"
down_revision = "0021_agent_run_failure_origin"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create defaults only for assignments that do not already exist.

    The original 0019 seed is identifiable by its own ``updated_by`` value.  Only
    that known migration-owned state may be normalized.  Every other existing row
    may be an operator selection and remains untouched during an upgrade.
    """
    op.execute("SET ROLE factory_migration_owner")
    op.execute(
        """
        INSERT INTO agent_runtime.model_assignments (
            consumer_id, data_classification, model_id, selection_mode,
            selection_policy, updated_by
        ) VALUES
            ('agent', 0, 'local_quality', 'MANUAL', NULL, 'migration:0022'),
            ('agent', 1, 'local_quality', 'MANUAL', NULL, 'migration:0022'),
            ('agent', 2, 'local_quality', 'MANUAL', NULL, 'migration:0022'),
            ('agent', 3, 'local_quality', 'MANUAL', NULL, 'migration:0022'),
            ('rca.reasoning', 0, 'local_quality', 'MANUAL', NULL, 'migration:0022'),
            ('rca.reasoning', 1, 'local_quality', 'MANUAL', NULL, 'migration:0022'),
            ('rca.reasoning', 2, 'local_quality', 'MANUAL', NULL, 'migration:0022'),
            ('rca.reasoning', 3, 'local_quality', 'MANUAL', NULL, 'migration:0022')
        ON CONFLICT (consumer_id, data_classification) DO UPDATE SET
            model_id = EXCLUDED.model_id,
            selection_mode = EXCLUDED.selection_mode,
            selection_policy = EXCLUDED.selection_policy,
            updated_at = CURRENT_TIMESTAMP,
            updated_by = EXCLUDED.updated_by
        WHERE agent_runtime.model_assignments.updated_by = 'migration:0019';
        """
    )
    op.execute("RESET ROLE")


def downgrade() -> None:
    """Keep user configuration intact when rolling back this data normalization."""

"""Normalize persisted default model assignments to local manual selection."""

from alembic import op

revision = "0022_normalize_local_model_assignment_defaults"
down_revision = "0021_agent_run_failure_origin"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Apply the one-time local default without creating a startup reset path."""
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
            updated_by = EXCLUDED.updated_by;
        """
    )
    op.execute("RESET ROLE")


def downgrade() -> None:
    """Keep user configuration intact when rolling back this data normalization."""

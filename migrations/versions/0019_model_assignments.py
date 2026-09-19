"""Add persistent model assignments without granting model authorization."""

from alembic import op

revision = "0019_model_assignments"
down_revision = "0018_agent_run_recovery_outcome"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("SET ROLE factory_migration_owner")
    op.execute(
        """
        CREATE TABLE agent_runtime.model_assignments (
            consumer_id TEXT NOT NULL,
            data_classification SMALLINT NOT NULL
                CHECK (data_classification BETWEEN 0 AND 3),
            model_id TEXT NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_by TEXT,
            PRIMARY KEY (consumer_id, data_classification),
            CHECK (consumer_id ~ '^[a-z][a-z0-9]*([._-][a-z0-9]+)*$'),
            CHECK (model_id ~ '^[a-z][a-z0-9_]*$')
        );

        INSERT INTO agent_runtime.model_assignments (
            consumer_id, data_classification, model_id, updated_by
        ) VALUES
            ('agent', 0, 'nvidia_quality', 'migration:0019'),
            ('agent', 1, 'nvidia_quality', 'migration:0019'),
            ('agent', 2, 'nvidia_quality', 'migration:0019'),
            ('rca.reasoning', 0, 'nvidia_quality', 'migration:0019'),
            ('rca.reasoning', 1, 'nvidia_quality', 'migration:0019'),
            ('rca.reasoning', 2, 'nvidia_quality', 'migration:0019'),
            ('rca.reasoning', 3, 'local_fast', 'migration:0019');

        GRANT SELECT, INSERT, UPDATE ON agent_runtime.model_assignments TO factory_app;
        """
    )
    op.execute("RESET ROLE")


def downgrade() -> None:
    op.execute("SET ROLE factory_migration_owner")
    op.execute("DROP TABLE agent_runtime.model_assignments")
    op.execute("RESET ROLE")

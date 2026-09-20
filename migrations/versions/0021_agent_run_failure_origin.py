"""Persist coarse failure attribution for agent runs."""

from alembic import op

revision = "0021_agent_run_failure_origin"
down_revision = "0020_model_selection_modes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("SET ROLE factory_migration_owner")
    op.execute(
        """
        ALTER TABLE agent_runtime.agent_runs
            ADD COLUMN failure_origin TEXT,
            ADD CONSTRAINT agent_runs_failure_origin_check CHECK (
                failure_origin IS NULL OR failure_origin IN (
                    'MODEL_SELECTION', 'MODEL_AVAILABILITY',
                    'CAPABILITY_VALIDATION', 'SECURITY_POLICY',
                    'PROVIDER_RATE_LIMIT', 'PROVIDER_CONNECTION',
                    'PROVIDER_REQUEST', 'MODEL_OUTPUT_VALIDATION',
                    'TOOL_EXECUTION', 'MCP', 'ORCHESTRATION', 'PERSISTENCE'
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
            DROP CONSTRAINT agent_runs_failure_origin_check,
            DROP COLUMN failure_origin;
        """
    )
    op.execute("RESET ROLE")

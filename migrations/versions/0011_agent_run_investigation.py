"""Group durable agent runs into ordered investigations."""

from alembic import op

revision = "0011_agent_run_investigation"
down_revision = "0010_agent_run_response_language"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("SET ROLE factory_migration_owner")
    op.execute(
        """
        ALTER TABLE agent_runtime.agent_runs
            ADD COLUMN investigation_id UUID,
            ADD COLUMN investigation_sequence INTEGER;

        -- FORCE RLS also applies to the migration owner. Temporarily disable the
        -- owner restriction only inside this transactional backfill.
        ALTER TABLE agent_runtime.agent_runs NO FORCE ROW LEVEL SECURITY;
        """
    )
    op.execute(
        """

        UPDATE agent_runtime.agent_runs
        SET investigation_id = run_id, investigation_sequence = 1
        WHERE investigation_id IS NULL;
        """
    )
    op.execute(
        """

        ALTER TABLE agent_runtime.agent_runs
            ALTER COLUMN investigation_id SET NOT NULL,
            ALTER COLUMN investigation_sequence SET NOT NULL,
            ADD CONSTRAINT agent_runs_investigation_sequence_positive
                CHECK (investigation_sequence > 0),
            ADD CONSTRAINT agent_runs_investigation_sequence_unique
                UNIQUE (investigation_id, investigation_sequence);
        CREATE INDEX agent_runs_investigation_idx
            ON agent_runtime.agent_runs (investigation_id, investigation_sequence);
        ALTER TABLE agent_runtime.agent_runs FORCE ROW LEVEL SECURITY;
        """
    )
    op.execute("RESET ROLE")


def downgrade() -> None:
    op.execute("SET ROLE factory_migration_owner")
    op.execute("DROP INDEX agent_runtime.agent_runs_investigation_idx")
    op.execute(
        """
        ALTER TABLE agent_runtime.agent_runs
            DROP CONSTRAINT agent_runs_investigation_sequence_unique,
            DROP CONSTRAINT agent_runs_investigation_sequence_positive,
            DROP COLUMN investigation_sequence,
            DROP COLUMN investigation_id;
        """
    )
    op.execute("RESET ROLE")

"""Create the isolated persistent agent-runtime namespace.

The LangGraph saver owns its framework tables.  This migration owns only the
application-facing run record and the schema permissions needed by the saver setup.
"""

from alembic import op

revision = "0002_agent_runtime"
down_revision = "0001_factory_data"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Existing demo volumes can predate the init-script database-level grant.
    # The database owner performs this idempotent compatibility grant before role drop.
    op.execute(
        """
        DO $$
        BEGIN
            EXECUTE format(
                'GRANT CREATE ON DATABASE %I TO factory_migration_owner',
                current_database()
            );
        END $$;
        """
    )
    op.execute("SET ROLE factory_migration_owner")
    op.execute(
        """
        CREATE SCHEMA agent_runtime AUTHORIZATION factory_migration_owner;
        CREATE SCHEMA langgraph_checkpoint AUTHORIZATION factory_migration_owner;

        CREATE TABLE agent_runtime.agent_runs (
            run_id UUID PRIMARY KEY,
            thread_id UUID NOT NULL UNIQUE,
            status TEXT NOT NULL CHECK (status IN (
                'running', 'waiting_for_approval', 'success', 'limit_reached', 'failed'
            )),
            data_classification SMALLINT NOT NULL CHECK (data_classification BETWEEN 0 AND 3),
            model_profile TEXT,
            request_text TEXT NOT NULL,
            final_answer TEXT,
            error_code TEXT,
            error_message TEXT,
            tool_call_summary JSONB NOT NULL DEFAULT '[]'::jsonb,
            interrupted_at TIMESTAMPTZ,
            completed_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX agent_runs_status_idx ON agent_runtime.agent_runs(status);
        CREATE INDEX agent_runs_created_at_idx ON agent_runtime.agent_runs(created_at DESC);

        ALTER TABLE agent_runtime.agent_runs ENABLE ROW LEVEL SECURITY;
        ALTER TABLE agent_runtime.agent_runs FORCE ROW LEVEL SECURITY;
        CREATE POLICY agent_runs_clearance_policy ON agent_runtime.agent_runs
        FOR ALL TO factory_app
        USING (
            data_classification <= COALESCE(
                NULLIF(current_setting('app.clearance', true), '')::SMALLINT,
                -1
            )
        )
        WITH CHECK (
            data_classification <= COALESCE(
                NULLIF(current_setting('app.clearance', true), '')::SMALLINT,
                -1
            )
        );
        GRANT USAGE ON SCHEMA agent_runtime, langgraph_checkpoint TO factory_app;
        GRANT SELECT, INSERT, UPDATE ON agent_runtime.agent_runs TO factory_app;
        GRANT CREATE ON SCHEMA langgraph_checkpoint TO factory_app;
        """
    )
    op.execute("RESET ROLE")


def downgrade() -> None:
    op.execute("SET ROLE factory_migration_owner")
    op.execute("DROP SCHEMA langgraph_checkpoint CASCADE")
    op.execute("DROP SCHEMA agent_runtime CASCADE")
    op.execute("RESET ROLE")

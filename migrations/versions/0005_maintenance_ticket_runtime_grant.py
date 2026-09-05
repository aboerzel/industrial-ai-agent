"""Grant the application role the approved maintenance-ticket write capability."""

from alembic import op

revision = "0005_maintenance_ticket_runtime_grant"
down_revision = "0004_agent_run_approval_payload"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("SET ROLE factory_migration_owner")
    op.execute("GRANT SELECT, INSERT, UPDATE ON maintenance_ticket TO factory_app")
    op.execute("RESET ROLE")


def downgrade() -> None:
    op.execute("SET ROLE factory_migration_owner")
    op.execute("REVOKE INSERT, UPDATE ON maintenance_ticket FROM factory_app")
    op.execute("RESET ROLE")

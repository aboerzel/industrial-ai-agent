"""Add the ticket write RLS policy for databases already at revision 0005."""

from alembic import op

revision = "0006_maintenance_ticket_insert_policy"
down_revision = "0005_maintenance_ticket_runtime_grant"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("SET ROLE factory_migration_owner")
    op.execute(
        """
        CREATE POLICY maintenance_ticket_insert_clearance_policy
            ON maintenance_ticket FOR INSERT TO factory_app
            WITH CHECK (
                classification <= COALESCE(
                    NULLIF(current_setting('app.clearance', true), '')::SMALLINT,
                    -1
                )
            );
        """
    )
    op.execute("RESET ROLE")


def downgrade() -> None:
    op.execute("SET ROLE factory_migration_owner")
    op.execute(
        "DROP POLICY maintenance_ticket_insert_clearance_policy ON maintenance_ticket"
    )
    op.execute("RESET ROLE")

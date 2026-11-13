"""Financial statements (docs/PLAN-CA-DESK-2.md #5): a firm's corrections of where a ledger goes in Schedule III, learned
and used for every later trial balance.

Revision ID: 0061
"""
from alembic import op

revision = "0061"
down_revision = "0060"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
    CREATE TABLE app.ca_ledger_map (
      id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      org_id      text NOT NULL,
      ledger_key  text NOT NULL,      -- the ledger name, lower case, spaces and punctuation squeezed
      line        text NOT NULL,      -- a finstat.LINES key
      created_by  text,
      created_at  timestamptz NOT NULL DEFAULT now(),
      UNIQUE (org_id, ledger_key)
    );
    ALTER TABLE app.ca_ledger_map ENABLE ROW LEVEL SECURITY;
    ALTER TABLE app.ca_ledger_map FORCE ROW LEVEL SECURITY;
    CREATE POLICY tenant_isolation ON app.ca_ledger_map USING (org_id = current_setting('app.org_id', true))
      WITH CHECK (org_id = current_setting('app.org_id', true));
    GRANT SELECT, INSERT, UPDATE, DELETE ON app.ca_ledger_map TO agentry_app, agentry_system;
    """)


def downgrade() -> None:
    op.execute("DROP TABLE app.ca_ledger_map;")

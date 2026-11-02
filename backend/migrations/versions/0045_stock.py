"""Stock shelf scanner (ROADMAP-V3 B2, v2 11.3): items with reorder levels, and the shelf photos that count them.

Revision ID: 0045
"""
from alembic import op

revision = "0045"
down_revision = "0044"
branch_labels = None
depends_on = None

TABLES = ["stock_items", "stock_scans"]


def upgrade() -> None:
    op.execute("""
    CREATE TABLE app.stock_items (
      id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      org_id          text NOT NULL,
      name            text NOT NULL,
      unit            text NOT NULL DEFAULT 'pc',
      reorder_at      numeric(12,2) NOT NULL DEFAULT 0,
      reorder_qty     numeric(12,2) NOT NULL DEFAULT 0,
      supplier        text,
      supplier_phone  text,
      count           numeric(12,2),
      counted_at      timestamptz,
      created_at      timestamptz NOT NULL DEFAULT now()
    );
    CREATE UNIQUE INDEX stock_items_name ON app.stock_items (org_id, lower(name));
    CREATE TABLE app.stock_scans (
      id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      org_id      text NOT NULL,
      path        text NOT NULL,
      area        text,
      items       jsonb NOT NULL DEFAULT '[]',   -- [{name, count, unit, confidence, item_id, previous}]
      status      text NOT NULL DEFAULT 'review' CHECK (status IN ('review','applied','discarded')),
      created_by  text,
      created_at  timestamptz NOT NULL DEFAULT now()
    );
    """)
    for t in TABLES:
        op.execute(f"""
        ALTER TABLE app.{t} ENABLE ROW LEVEL SECURITY;
        ALTER TABLE app.{t} FORCE ROW LEVEL SECURITY;
        CREATE POLICY tenant_isolation ON app.{t} USING (org_id = current_setting('app.org_id', true))
          WITH CHECK (org_id = current_setting('app.org_id', true));
        GRANT SELECT, INSERT, UPDATE, DELETE ON app.{t} TO agentry_app, agentry_system;
        """)


def downgrade() -> None:
    op.execute("DROP TABLE app.stock_scans; DROP TABLE app.stock_items;")

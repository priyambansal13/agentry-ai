"""Catalogue & quotes (ROADMAP-V3 A3): the products a business sells and the quotes the agent makes from them.

Revision ID: 0039
"""
from alembic import op

revision = "0039"
down_revision = "0038"
branch_labels = None
depends_on = None

TABLES = ["products", "quotes"]


def upgrade() -> None:
    op.execute("""
    CREATE TABLE app.products (
      id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      org_id      text NOT NULL,
      code        text NOT NULL,
      name        text NOT NULL,
      description text,
      category    text,
      unit        text NOT NULL DEFAULT 'pc',
      price       numeric(14,2) NOT NULL CHECK (price >= 0),
      gst_rate    numeric(5,2) NOT NULL DEFAULT 18,
      stock       numeric(14,2),
      min_qty     numeric(14,2) NOT NULL DEFAULT 1,
      active      boolean NOT NULL DEFAULT true,
      updated_at  timestamptz NOT NULL DEFAULT now(),
      UNIQUE (org_id, code)
    );
    CREATE INDEX ON app.products (org_id, lower(name));

    CREATE TABLE app.quotes (
      id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      org_id          text NOT NULL,
      number          text NOT NULL,
      token           text NOT NULL UNIQUE,
      contact_id      uuid REFERENCES app.contacts(id) ON DELETE SET NULL,
      conversation_id uuid REFERENCES app.conversations(id) ON DELETE SET NULL,
      customer        text NOT NULL,
      phone           text,
      email           text,
      items           jsonb NOT NULL,
      subtotal        numeric(14,2) NOT NULL,
      gst             numeric(14,2) NOT NULL,
      total           numeric(14,2) NOT NULL,
      currency        text NOT NULL DEFAULT 'INR',
      valid_until     date NOT NULL,
      note            text,
      status          text NOT NULL DEFAULT 'draft' CHECK (status IN ('draft','sent','won','lost','expired')),
      source          text NOT NULL DEFAULT 'person' CHECK (source IN ('agent','person')),
      sent_at         timestamptz,
      followups       int NOT NULL DEFAULT 0,
      last_followup_at timestamptz,
      decided_at      timestamptz,
      created_by      text,
      created_at      timestamptz NOT NULL DEFAULT now(),
      UNIQUE (org_id, number)
    );
    CREATE INDEX ON app.quotes (org_id, status, created_at DESC);
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
    op.execute("DROP TABLE app.quotes; DROP TABLE app.products;")

"""Support desk (ROADMAP-V3 A2): customer issues as tickets with SLA, and the orders customers ask about.

Revision ID: 0038
"""
from alembic import op

revision = "0038"
down_revision = "0037"
branch_labels = None
depends_on = None

TABLES = ["tickets", "orders"]


def upgrade() -> None:
    op.execute("""
    CREATE TABLE app.tickets (
      id                uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      org_id            text NOT NULL,
      number            int NOT NULL,
      conversation_id   uuid REFERENCES app.conversations(id) ON DELETE SET NULL,
      contact_id        uuid REFERENCES app.contacts(id) ON DELETE SET NULL,
      channel           text,
      subject           text NOT NULL,
      summary           text,
      category          text NOT NULL DEFAULT 'other',
      priority          text NOT NULL DEFAULT 'normal' CHECK (priority IN ('low','normal','high','urgent')),
      status            text NOT NULL DEFAULT 'open' CHECK (status IN ('open','waiting_customer','resolved','closed')),
      assignee          text,
      order_ref         text,
      sla_due_at        timestamptz,
      first_response_at timestamptz,
      resolved_at       timestamptz,
      breached_at       timestamptz,
      csat              int CHECK (csat BETWEEN 1 AND 5),
      csat_asked_at     timestamptz,
      notes             jsonb NOT NULL DEFAULT '[]',
      source            text NOT NULL DEFAULT 'agent' CHECK (source IN ('agent','handoff','person','email')),
      created_at        timestamptz NOT NULL DEFAULT now(),
      updated_at        timestamptz NOT NULL DEFAULT now(),
      UNIQUE (org_id, number)
    );
    CREATE INDEX ON app.tickets (org_id, status, sla_due_at);

    CREATE TABLE app.orders (
      id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      org_id       text NOT NULL,
      order_ref    text NOT NULL,
      customer     text,
      phone        text,
      email        text,
      status       text NOT NULL,
      items        text,
      amount       numeric(14,2),
      eta          date,
      tracking_url text,
      updated_at   timestamptz NOT NULL DEFAULT now(),
      UNIQUE (org_id, order_ref)
    );
    CREATE INDEX ON app.orders (org_id, right(regexp_replace(coalesce(phone, ''), '\\D', '', 'g'), 10));
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
    op.execute("DROP TABLE app.orders; DROP TABLE app.tickets;")

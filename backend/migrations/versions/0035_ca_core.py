"""CA Firm pack core (docs/PACKS.md): the firm's own clients, every filing on a board, and the files clients send.

Revision ID: 0035
"""
from alembic import op

revision = "0035"
down_revision = "0034"
branch_labels = None
depends_on = None

TABLES = ["ca_clients", "ca_filings", "ca_files"]
KINDS = "'reply_draft','outbound_draft','escalation','dispute','low_confidence','handoff','payment_review','callback','document_review'"


def upgrade() -> None:
    op.execute("""
    -- the CA firm's clients (people and businesses whose returns the firm files)
    CREATE TABLE app.ca_clients (
      id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      org_id      text NOT NULL,
      contact_id  uuid REFERENCES app.contacts(id) ON DELETE SET NULL,
      name        text NOT NULL,
      kind        text NOT NULL DEFAULT 'individual' CHECK (kind IN ('individual','huf','firm','llp','company','trust')),
      pan         text,
      gstin       text,
      phone       text,
      email       text,
      profile     jsonb NOT NULL DEFAULT '{}',  -- salaried, business, capital_gains, house_property, rent_paid, gst, tds, audit...
      assignee    text,                          -- auth user id of the staff member who looks after them
      notes       text,
      created_at  timestamptz NOT NULL DEFAULT now(),
      updated_at  timestamptz NOT NULL DEFAULT now()
    );
    CREATE UNIQUE INDEX ca_clients_pan ON app.ca_clients (org_id, upper(pan)) WHERE pan IS NOT NULL;
    CREATE INDEX ON app.ca_clients (org_id, lower(name));

    -- one card per filing (ITR AY 2026-27, GSTR-3B 2026-10, a notice reply...)
    CREATE TABLE app.ca_filings (
      id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      org_id        text NOT NULL,
      client_id     uuid NOT NULL REFERENCES app.ca_clients(id) ON DELETE CASCADE,
      kind          text NOT NULL,
      period        text NOT NULL,
      title         text NOT NULL,
      due_on        date,
      status        text NOT NULL DEFAULT 'docs_pending'
                    CHECK (status IN ('docs_pending','in_prep','review','filed','verified')),
      assignee      text,
      ack_no        text,
      filed_on      date,
      notes         text,
      checklist     jsonb NOT NULL DEFAULT '[]',   -- document chaser: [{key, label, status, file_ids, received_at}]
      chase         jsonb NOT NULL DEFAULT '{}',   -- {sent: n, last_at, paused}
      data          jsonb NOT NULL DEFAULT '{}',   -- what the CA agents worked out for this filing
      source        text NOT NULL DEFAULT 'manual' CHECK (source IN ('manual','season','calendar','notice')),
      position      int NOT NULL DEFAULT 0,
      status_at     timestamptz NOT NULL DEFAULT now(),
      created_at    timestamptz NOT NULL DEFAULT now(),
      updated_at    timestamptz NOT NULL DEFAULT now(),
      UNIQUE (org_id, client_id, kind, period)
    );
    CREATE INDEX ON app.ca_filings (org_id, status, due_on);

    -- files a client sent or the firm uploaded (Form 16, AIS, bank statements, notices...)
    CREATE TABLE app.ca_files (
      id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      org_id      text NOT NULL,
      client_id   uuid NOT NULL REFERENCES app.ca_clients(id) ON DELETE CASCADE,
      filing_id   uuid REFERENCES app.ca_filings(id) ON DELETE SET NULL,
      item_key    text,                -- the checklist item it answers
      doc_type    text,                -- form16, ais, 26as, tis, bank_statement, broker_pnl, notice, gstr2b, purchase_register...
      filename    text,
      mime        text NOT NULL,
      path        text NOT NULL,
      bytes       int NOT NULL,
      sha256      text NOT NULL,
      source      text NOT NULL DEFAULT 'portal' CHECK (source IN ('portal','whatsapp','telegram','email')),
      extracted   jsonb,               -- what a reader agent took out of it, with the source line of every number
      created_by  text,
      created_at  timestamptz NOT NULL DEFAULT now()
    );
    CREATE INDEX ON app.ca_files (org_id, client_id, created_at DESC);
    """)
    for t in TABLES:
        op.execute(f"""
        ALTER TABLE app.{t} ENABLE ROW LEVEL SECURITY;
        ALTER TABLE app.{t} FORCE ROW LEVEL SECURITY;
        CREATE POLICY tenant_isolation ON app.{t} USING (org_id = current_setting('app.org_id', true))
          WITH CHECK (org_id = current_setting('app.org_id', true));
        GRANT SELECT, INSERT, UPDATE, DELETE ON app.{t} TO agentry_app, agentry_system;
        """)
    op.execute(f"""
    ALTER TABLE app.approvals DROP CONSTRAINT approvals_kind_check;
    ALTER TABLE app.approvals ADD CONSTRAINT approvals_kind_check CHECK (kind IN ({KINDS},'ca_task'));
    """)


def downgrade() -> None:
    op.execute(f"""
    DELETE FROM app.approvals WHERE kind = 'ca_task';
    ALTER TABLE app.approvals DROP CONSTRAINT approvals_kind_check;
    ALTER TABLE app.approvals ADD CONSTRAINT approvals_kind_check CHECK (kind IN ({KINDS}));
    DROP TABLE app.ca_files; DROP TABLE app.ca_filings; DROP TABLE app.ca_clients;
    """)

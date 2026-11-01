"""CA Firm pack, agents 5-13: what each agent worked out (a reconciliation, a computation, a classified statement…),
the bank-statement categories the firm taught it, and recurring bookkeeping entries.

Revision ID: 0036
"""
from alembic import op

revision = "0036"
down_revision = "0035"
branch_labels = None
depends_on = None

TABLES = ["ca_work", "ca_bank_rules", "recurring_entries"]
SOURCES = "'upload','whatsapp','telegram','email','sample'"


def upgrade() -> None:
    op.execute(f"""
    CREATE TABLE app.ca_work (
      id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      org_id      text NOT NULL,
      client_id   uuid REFERENCES app.ca_clients(id) ON DELETE CASCADE,  -- null: the firm's own (Excel desk)
      agent       text NOT NULL,
      title       text NOT NULL,
      file_ids    uuid[] NOT NULL DEFAULT '{{}}',
      params      jsonb NOT NULL DEFAULT '{{}}',
      result      jsonb NOT NULL DEFAULT '{{}}',
      created_by  text,
      created_at  timestamptz NOT NULL DEFAULT now(),
      updated_at  timestamptz NOT NULL DEFAULT now()
    );
    CREATE INDEX ON app.ca_work (org_id, client_id, agent, created_at DESC);

    -- "a statement line containing this means that category" (bank statement classifier; learned from corrections)
    CREATE TABLE app.ca_bank_rules (
      id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      org_id      text NOT NULL,
      pattern     text NOT NULL,
      category    text NOT NULL,
      created_by  text,
      created_at  timestamptz NOT NULL DEFAULT now(),
      UNIQUE (org_id, pattern)
    );

    -- rent, retainers, EMIs, subscriptions: booked into the books on their dates
    CREATE TABLE app.recurring_entries (
      id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      org_id         text NOT NULL,
      name           text NOT NULL,
      vendor         text NOT NULL,
      category       text NOT NULL,
      amount         numeric(14,2) NOT NULL CHECK (amount > 0),
      gst_rate       numeric(5,2) NOT NULL DEFAULT 0,
      frequency      text NOT NULL CHECK (frequency IN ('weekly','monthly','quarterly','yearly')),
      next_on        date NOT NULL,
      ends_on        date,
      active         boolean NOT NULL DEFAULT true,
      last_booked_on date,
      created_by     text,
      created_at     timestamptz NOT NULL DEFAULT now()
    );
    ALTER TABLE app.documents DROP CONSTRAINT documents_source_check;
    ALTER TABLE app.documents ADD CONSTRAINT documents_source_check CHECK (source IN ({SOURCES},'recurring'));
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
    op.execute(f"""
    DELETE FROM app.documents WHERE source = 'recurring';
    ALTER TABLE app.documents DROP CONSTRAINT documents_source_check;
    ALTER TABLE app.documents ADD CONSTRAINT documents_source_check CHECK (source IN ({SOURCES}));
    DROP TABLE app.recurring_entries; DROP TABLE app.ca_bank_rules; DROP TABLE app.ca_work;
    """)

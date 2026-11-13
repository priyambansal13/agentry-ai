"""Balance confirmations (docs/PLAN-CA-DESK-2.md #7): one row per debtor / creditor asked to confirm their balance with a
client, for the audit file. The request batch is a piece of work (app.ca_work, agent ca_balance_confirmations).

Revision ID: 0062
"""
from alembic import op

revision = "0062"
down_revision = "0061"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
    CREATE TABLE app.ca_confirmations (
      id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      org_id          text NOT NULL,
      client_id       uuid NOT NULL REFERENCES app.ca_clients(id) ON DELETE CASCADE,
      work_id         uuid NOT NULL REFERENCES app.ca_work(id) ON DELETE CASCADE,
      party           text NOT NULL,
      kind            text NOT NULL CHECK (kind IN ('debtor','creditor')),
      email           text,
      our_balance     numeric(16,2) NOT NULL,          -- in the client's books, debit +
      as_of           date NOT NULL,
      token_hashes    text[] NOT NULL DEFAULT '{}',    -- the private reply links sent (a reminder adds one; all keep working)
      expires_at      timestamptz,
      status          text NOT NULL DEFAULT 'draft' CHECK (status IN ('draft','not_selected','no_email','sent','agreed','differs','unclear')),
      sent_at         timestamptz,
      sent_via        text,                            -- gmail / outlook / recorded (no mailbox, or a test address)
      reminders       int NOT NULL DEFAULT 0,
      last_sent_at    timestamptz,
      replied_at      timestamptz,
      reply_via       text CHECK (reply_via IN ('link','email','manual')),
      their_balance   numeric(16,2),                   -- as the party gives it (amount, no sign)
      reply_note      text,
      reply_read_by   text,                            -- rules / ai / party / staff
      reply_file_id   uuid,
      created_at      timestamptz NOT NULL DEFAULT now()
    );
    CREATE INDEX ON app.ca_confirmations (org_id, work_id);
    CREATE INDEX ca_confirmations_tokens ON app.ca_confirmations USING gin (token_hashes);
    ALTER TABLE app.ca_confirmations ENABLE ROW LEVEL SECURITY;
    ALTER TABLE app.ca_confirmations FORCE ROW LEVEL SECURITY;
    CREATE POLICY tenant_isolation ON app.ca_confirmations USING (org_id = current_setting('app.org_id', true))
      WITH CHECK (org_id = current_setting('app.org_id', true));
    GRANT SELECT, INSERT, UPDATE, DELETE ON app.ca_confirmations TO agentry_app, agentry_system;
    ALTER TABLE app.ca_files DROP CONSTRAINT ca_files_source_check;
    ALTER TABLE app.ca_files ADD CONSTRAINT ca_files_source_check CHECK (source IN ('portal','whatsapp','telegram','email','client_portal','confirmation'));
    """)


def downgrade() -> None:
    op.execute("""DROP TABLE app.ca_confirmations;
      DELETE FROM app.ca_files WHERE source = 'confirmation';
      ALTER TABLE app.ca_files DROP CONSTRAINT ca_files_source_check;
      ALTER TABLE app.ca_files ADD CONSTRAINT ca_files_source_check CHECK (source IN ('portal','whatsapp','telegram','email','client_portal'));""")

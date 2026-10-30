"""Cold email sending and replies (Phase 5.4-5.5): sending mailboxes with caps and health, each prospect's place in
the sequence, and every send, bounce, reply and unsubscribe as an event.

Revision ID: 0018
"""
from alembic import op

revision = "0018"
down_revision = "0017"
branch_labels = None
depends_on = None

TENANT_TABLES = ["sending_mailboxes", "email_events"]


def upgrade() -> None:
    op.execute("""
    CREATE TABLE app.sending_mailboxes (
      id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      org_id        text NOT NULL,
      address       text NOT NULL,                 -- on a separate sending domain, never the client's main domain
      provider      text NOT NULL CHECK (provider IN ('mock','instantly')),
      sender_name   text NOT NULL,                 -- the person the emails are from
      daily_cap     int NOT NULL DEFAULT 30 CHECK (daily_cap BETWEEN 1 AND 100),
      start_cap     int NOT NULL DEFAULT 5,        -- ramp-up: start_cap on day 1, + ramp_per_day each day, up to daily_cap
      ramp_per_day  int NOT NULL DEFAULT 3,
      started_at    timestamptz NOT NULL DEFAULT now(),
      status        text NOT NULL DEFAULT 'active' CHECK (status IN ('active','paused')),
      paused_reason text,
      created_at    timestamptz NOT NULL DEFAULT now(),
      UNIQUE (org_id, address)
    );

    ALTER TABLE app.prospects
      ADD COLUMN status        text NOT NULL DEFAULT 'waiting'
                               CHECK (status IN ('waiting','active','finished','stopped')),
      ADD COLUMN next_step     int NOT NULL DEFAULT 0,
      ADD COLUMN next_send_at  timestamptz,
      ADD COLUMN mailbox_id    uuid REFERENCES app.sending_mailboxes(id),
      ADD COLUMN stop_reason   text,
      ADD COLUMN reply_kind    text,
      ADD COLUMN nurture_at    timestamptz,
      ADD COLUMN lead_id       uuid,
      ADD COLUMN conversation_id uuid;
    CREATE INDEX ON app.prospects (org_id, status, next_send_at);

    CREATE TABLE app.email_events (
      id           bigserial PRIMARY KEY,
      org_id       text NOT NULL,
      campaign_id  uuid REFERENCES app.campaigns(id) ON DELETE CASCADE,
      prospect_id  uuid REFERENCES app.prospects(id) ON DELETE CASCADE,
      mailbox_id   uuid REFERENCES app.sending_mailboxes(id),
      kind         text NOT NULL CHECK (kind IN ('sent','bounce','reply','complaint','unsubscribe')),
      step         int,
      detail       jsonb NOT NULL DEFAULT '{}',    -- subject, body, message id, reply text and its classification
      at           timestamptz NOT NULL DEFAULT now()
    );
    CREATE INDEX ON app.email_events (org_id, mailbox_id, kind, at);
    CREATE INDEX ON app.email_events (prospect_id);
    """)
    for t in TENANT_TABLES:
        op.execute(f"""
        ALTER TABLE app.{t} ENABLE ROW LEVEL SECURITY;
        ALTER TABLE app.{t} FORCE ROW LEVEL SECURITY;
        CREATE POLICY tenant_isolation ON app.{t}
          USING (org_id = current_setting('app.org_id', true)) WITH CHECK (org_id = current_setting('app.org_id', true));
        GRANT SELECT, INSERT, UPDATE, DELETE ON app.{t} TO agentry_app, agentry_system;
        """)
    op.execute("GRANT USAGE ON SEQUENCE app.email_events_id_seq TO agentry_app, agentry_system;")


def downgrade() -> None:
    op.execute("""
    DROP TABLE app.email_events;
    ALTER TABLE app.prospects DROP COLUMN status, DROP COLUMN next_step, DROP COLUMN next_send_at, DROP COLUMN mailbox_id,
      DROP COLUMN stop_reason, DROP COLUMN reply_kind, DROP COLUMN nurture_at, DROP COLUMN lead_id, DROP COLUMN conversation_id;
    DROP TABLE app.sending_mailboxes;
    """)

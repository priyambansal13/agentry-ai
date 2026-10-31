"""Notification Center (ROADMAP-V2 §2.1): any event, to the right people, on the right channel.

    notification_rules  when <event> [conditions] tell <roles / people / the card's assignee> on <channels>,
                        now or in a daily digest; "critical" ignores quiet hours. Business rules (owners and managers)
                        and personal rules (anyone, for themselves).
    notifications       one row per person per event: the in-app bell's history and the delivery log
                        (deliveries: [{channel, status, error, at}]). Unique per (event, person): never twice.

Revision ID: 0021
"""
from alembic import op

revision = "0021"
down_revision = "0020"
branch_labels = None
depends_on = None

TENANT_TABLES = ["notification_rules", "notifications"]


def upgrade() -> None:
    op.execute("""
    CREATE TABLE app.notification_rules (
      id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      org_id      text NOT NULL,
      name        text NOT NULL,
      event_type  text NOT NULL,
      conditions  jsonb NOT NULL DEFAULT '[]',        -- [{field, op: gt|gte|lt|lte|eq|ne|in|contains, value}]
      roles       text[] NOT NULL DEFAULT '{}',        -- business rules: these roles (who may see the event)
      user_ids    text[] NOT NULL DEFAULT '{}',        -- and/or these people
      assignee    boolean NOT NULL DEFAULT false,     -- and/or the person a card is assigned to
      channels    text[] NOT NULL DEFAULT '{in_app}', -- in order of preference: telegram, whatsapp, email, in_app
      cadence     text NOT NULL DEFAULT 'now' CHECK (cadence IN ('now','digest')),
      digest_hour int NOT NULL DEFAULT 18 CHECK (digest_hour BETWEEN 0 AND 23),
      critical    boolean NOT NULL DEFAULT false,
      enabled     boolean NOT NULL DEFAULT true,
      owner_user  text,                               -- set: a personal rule (only that person, and only they edit it)
      is_default  boolean NOT NULL DEFAULT false,
      created_by  text,
      created_at  timestamptz NOT NULL DEFAULT now(),
      updated_at  timestamptz NOT NULL DEFAULT now()
    );
    CREATE INDEX ON app.notification_rules (org_id, event_type) WHERE enabled;

    CREATE TABLE app.notifications (
      id          bigserial PRIMARY KEY,
      org_id      text NOT NULL,
      user_id     text NOT NULL,
      event_id    bigint NOT NULL,
      event_type  text NOT NULL,
      rule_id     uuid REFERENCES app.notification_rules(id) ON DELETE SET NULL,
      title       text NOT NULL,
      body        text NOT NULL DEFAULT '',
      link        text,
      critical    boolean NOT NULL DEFAULT false,
      status      text NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','sent','held','digest','failed','in_app_only')),
      deliver_after timestamptz,                      -- quiet hours / digest: not before this
      deliveries  jsonb NOT NULL DEFAULT '[]',
      read_at     timestamptz,
      created_at  timestamptz NOT NULL DEFAULT now(),
      sent_at     timestamptz,
      UNIQUE (org_id, user_id, event_id)
    );
    CREATE INDEX ON app.notifications (org_id, user_id, created_at DESC);
    CREATE INDEX ON app.notifications (status, deliver_after) WHERE status IN ('held','digest');
    """)
    for t in TENANT_TABLES:
        op.execute(f"""
        ALTER TABLE app.{t} ENABLE ROW LEVEL SECURITY;
        ALTER TABLE app.{t} FORCE ROW LEVEL SECURITY;
        CREATE POLICY tenant_isolation ON app.{t}
          USING (org_id = current_setting('app.org_id', true)) WITH CHECK (org_id = current_setting('app.org_id', true));
        GRANT SELECT, INSERT, UPDATE, DELETE ON app.{t} TO agentry_app, agentry_system;
        """)
    op.execute("GRANT USAGE ON SEQUENCE app.notifications_id_seq TO agentry_app, agentry_system;")


def downgrade() -> None:
    op.execute("DROP TABLE app.notifications; DROP TABLE app.notification_rules;")

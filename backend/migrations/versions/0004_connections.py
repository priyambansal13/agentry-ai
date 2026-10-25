"""Connections to external accounts (Gmail, WhatsApp, later Outlook), with encrypted credentials.

Revision ID: 0004
"""
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
    CREATE TABLE app.connections (
      id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      org_id        text NOT NULL,
      provider      text NOT NULL CHECK (provider IN ('gmail','outlook','whatsapp')),
      account_ref   text NOT NULL,                 -- gmail address, or WhatsApp phone_number_id
      display_name  text,                          -- e.g. the WhatsApp display phone number
      status        text NOT NULL DEFAULT 'connected' CHECK (status IN ('connected','error','revoked')),
      secret_enc    text NOT NULL,                 -- Fernet-encrypted JSON (refresh/access tokens); never sent to browsers
      scopes        text[] NOT NULL DEFAULT '{}',
      state         jsonb NOT NULL DEFAULT '{}',   -- sync cursors (gmail historyId), label ids, waba id ...
      last_sync_at  timestamptz,
      last_error    text,
      connected_by  text,
      created_at    timestamptz NOT NULL DEFAULT now(),
      UNIQUE (org_id, provider, account_ref)
    );
    -- Webhooks arrive with only the provider's account id (e.g. WhatsApp phone_number_id): it must map to one org.
    CREATE UNIQUE INDEX connections_provider_account ON app.connections (provider, account_ref) WHERE status <> 'revoked';

    ALTER TABLE app.connections ENABLE ROW LEVEL SECURITY;
    ALTER TABLE app.connections FORCE ROW LEVEL SECURITY;
    CREATE POLICY tenant_isolation ON app.connections
      USING (org_id = current_setting('app.org_id', true)) WITH CHECK (org_id = current_setting('app.org_id', true));
    GRANT SELECT, INSERT, UPDATE, DELETE ON app.connections TO agentry_app, agentry_system;

    -- Inbound provider message ids, so a redelivered webhook or a re-synced email is processed once.
    CREATE UNIQUE INDEX messages_external_id ON app.messages (org_id, (metadata->>'external_id'))
      WHERE metadata ? 'external_id';

    ALTER TABLE app.conversations DROP CONSTRAINT conversations_channel_check;
    ALTER TABLE app.conversations ADD CONSTRAINT conversations_channel_check
      CHECK (channel IN ('email','web_chat','whatsapp','sms','voice'));
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS app.connections; DROP INDEX IF EXISTS app.messages_external_id;")

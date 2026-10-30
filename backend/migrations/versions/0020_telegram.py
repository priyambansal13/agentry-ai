"""Telegram: a customer channel (each business's own bot answers its customers, like WhatsApp) and Agentry's team
bot (alerts, Needs-you cards with buttons, a Tools menu for every agent).

    telegram_links       which Telegram chat belongs to which team member, in which business (one chat can serve several)
    telegram_link_codes  one-time codes behind the "Connect Telegram" deep link (Telegram allows 64 characters)
    telegram_offsets     where polling got to, per bot (local development has no public address for webhooks)
    approval.created     every new Needs-you card raises an event, so the team bot can push it (cards are created in
                         many places, so a trigger does it)

Revision ID: 0020
"""
from alembic import op

revision = "0020"
down_revision = "0019"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
    ALTER TABLE app.conversations DROP CONSTRAINT conversations_channel_check;
    ALTER TABLE app.conversations ADD CONSTRAINT conversations_channel_check
      CHECK (channel IN ('email','web_chat','whatsapp','sms','voice','telegram'));

    ALTER TABLE app.connections DROP CONSTRAINT connections_provider_check;
    ALTER TABLE app.connections ADD CONSTRAINT connections_provider_check
      CHECK (provider IN ('gmail','outlook','whatsapp','razorpay','stripe','phone','telegram'));

    CREATE TABLE app.telegram_links (
      org_id      text NOT NULL,
      user_id     text NOT NULL,
      chat_id     bigint NOT NULL,
      username    text,
      active      boolean NOT NULL DEFAULT true,      -- the business this chat is working in right now
      pending     jsonb,                              -- e.g. {"edit": "<approval id>"}: the next message is the new text
      linked_at   timestamptz NOT NULL DEFAULT now(),
      PRIMARY KEY (org_id, user_id)
    );
    CREATE INDEX ON app.telegram_links (chat_id);
    ALTER TABLE app.telegram_links ENABLE ROW LEVEL SECURITY;
    ALTER TABLE app.telegram_links FORCE ROW LEVEL SECURITY;
    CREATE POLICY tenant_isolation ON app.telegram_links
      USING (org_id = current_setting('app.org_id', true)) WITH CHECK (org_id = current_setting('app.org_id', true));
    GRANT SELECT, INSERT, UPDATE, DELETE ON app.telegram_links TO agentry_app, agentry_system;

    CREATE TABLE app.telegram_link_codes (
      code        text PRIMARY KEY,
      org_id      text NOT NULL,
      user_id     text NOT NULL,
      expires_at  timestamptz NOT NULL
    );
    GRANT SELECT, INSERT, UPDATE, DELETE ON app.telegram_link_codes TO agentry_app, agentry_system;

    CREATE TABLE app.telegram_offsets (
      bot         text PRIMARY KEY,                   -- 'agentry' or a connection id
      update_id   bigint NOT NULL DEFAULT 0
    );
    GRANT SELECT, INSERT, UPDATE, DELETE ON app.telegram_offsets TO agentry_system;

    CREATE FUNCTION app.announce_card() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      INSERT INTO app.events (org_id, type, payload)
      VALUES (NEW.org_id, 'approval.created', jsonb_build_object('approval_id', NEW.id, 'kind', NEW.kind));
      RETURN NEW;
    END $$;
    CREATE TRIGGER announce_card AFTER INSERT ON app.approvals FOR EACH ROW EXECUTE FUNCTION app.announce_card();
    """)


def downgrade() -> None:
    op.execute("""
    DROP TRIGGER announce_card ON app.approvals; DROP FUNCTION app.announce_card();
    DROP TABLE app.telegram_offsets; DROP TABLE app.telegram_link_codes; DROP TABLE app.telegram_links;
    DELETE FROM app.conversations WHERE channel = 'telegram';
    DELETE FROM app.connections WHERE provider = 'telegram';
    ALTER TABLE app.connections DROP CONSTRAINT connections_provider_check;
    ALTER TABLE app.connections ADD CONSTRAINT connections_provider_check
      CHECK (provider IN ('gmail','outlook','whatsapp','razorpay','stripe','phone'));
    ALTER TABLE app.conversations DROP CONSTRAINT conversations_channel_check;
    ALTER TABLE app.conversations ADD CONSTRAINT conversations_channel_check CHECK (channel IN ('email','web_chat','whatsapp','sms','voice'));
    """)

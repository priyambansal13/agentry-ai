"""Missed-call recovery (docs/PLAN-COMMERCIAL-2026-11.md #2): every missed call, the WhatsApp it got, and what came of it.

Revision ID: 0058
"""
from alembic import op

revision = "0058"
down_revision = "0057"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
    CREATE TABLE app.missed_calls (
      id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      org_id          text NOT NULL,
      caller          text NOT NULL,                 -- E.164
      called          text,                          -- the business's number that was called
      status          text NOT NULL,                 -- what the phone system said: no-answer / busy / missed / ...
      provider        text,
      contact_id      uuid REFERENCES app.contacts(id) ON DELETE SET NULL,
      outcome         text NOT NULL DEFAULT 'waiting' CHECK (outcome IN ('waiting','sent','skipped','failed')),
      skip_reason     text,
      conversation_id uuid,
      replied_at      timestamptz,
      booking_id      uuid,
      booked_at       timestamptz,
      raw             jsonb NOT NULL DEFAULT '{}',
      at              timestamptz NOT NULL DEFAULT now(),
      sent_at         timestamptz
    );
    CREATE INDEX ON app.missed_calls (org_id, at DESC);
    CREATE INDEX ON app.missed_calls (org_id, contact_id, at DESC);
    ALTER TABLE app.missed_calls ENABLE ROW LEVEL SECURITY;
    ALTER TABLE app.missed_calls FORCE ROW LEVEL SECURITY;
    CREATE POLICY tenant_isolation ON app.missed_calls USING (org_id = current_setting('app.org_id', true))
      WITH CHECK (org_id = current_setting('app.org_id', true));
    GRANT SELECT, INSERT, UPDATE, DELETE ON app.missed_calls TO agentry_app, agentry_system;
    -- the Clinic growth plan includes it (on)
    UPDATE app.agent_packs SET agents = agents || '[{"key": "missed_call_recovery", "default_on": true}]'::jsonb,
      highlights = '["Everything in Starter", "Every missed call gets a WhatsApp in a minute", "Appointment reminders, confirmations and a waitlist", "Review requests and replies", "Monthly check of what ChatGPT says about you"]'::jsonb
      WHERE key = 'clinic-growth' AND NOT agents @> '[{"key": "missed_call_recovery"}]'::jsonb;
    """)


def downgrade() -> None:
    op.execute("""DROP TABLE app.missed_calls;
      UPDATE app.agent_packs SET agents = (select coalesce(jsonb_agg(a), '[]') from jsonb_array_elements(agents) a where a->>'key' <> 'missed_call_recovery')
      WHERE key = 'clinic-growth';""")

"""Self-serve start (docs/PLAN-COMMERCIAL-2026-11.md #1): plans a visitor can buy on the website, and their sign-ups.

Revision ID: 0057
"""
import json

from alembic import op

revision = "0057"
down_revision = "0056"
branch_labels = None
depends_on = None

STARTER = [("website_chat", True), ("whatsapp_assistant", True), ("speed_to_lead", True)]
CLINIC = [("whatsapp_assistant", True), ("website_chat", True), ("appointment_concierge", True), ("reviews", True), ("speed_to_lead", True),
          ("ai_visibility", False), ("ai_receptionist", False)]


def plan(retainer: str, setup: str, messages: int, usd: str) -> dict:
    return {"INR": {"currency": "INR", "setup_fee": setup, "retainer": retainer, "included": {"messages": messages},
                    "overage": {"messages": "1.50"}, "tax_rate": 0.18},
            "USD": {"currency": "USD", "setup_fee": "0", "retainer": usd, "included": {"messages": messages}, "overage": {"messages": "0.03"}, "tax_rate": 0}}


def upgrade() -> None:
    op.execute("""
    ALTER TABLE app.agent_packs ADD COLUMN self_serve boolean NOT NULL DEFAULT false,  -- on the website's /start
                                ADD COLUMN sort int NOT NULL DEFAULT 100,
                                ADD COLUMN highlights jsonb NOT NULL DEFAULT '[]';    -- what the plan card lists
    -- a visitor buying a plan on the website: paid -> email link -> the portal makes the account -> provisioned
    CREATE TABLE app.signups (
      id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      pack            text NOT NULL REFERENCES app.agent_packs(key) ON UPDATE CASCADE,
      business        text NOT NULL,
      website         text,
      name            text NOT NULL,
      email           text NOT NULL,
      phone           text,
      country         text NOT NULL DEFAULT 'IN',
      currency        text NOT NULL DEFAULT 'INR',
      amount          numeric(12,2) NOT NULL,        -- first payment: setup + first month + tax
      status          text NOT NULL DEFAULT 'pending_payment'
                      CHECK (status IN ('pending_payment','paid','claimed','provisioned','cancelled','failed')),
      token_hash      text NOT NULL,                 -- the emailed link's secret (hashed, to check it)
      token_enc       text NOT NULL,                 -- the same, encrypted (to email it once paid)
      payment_link    text,
      payment_ref     text,
      paid_at         timestamptz,
      org_id          text,                          -- set once, when the portal makes the account
      source          text,
      ip_hash         text,
      error           text,
      created_at      timestamptz NOT NULL DEFAULT now(),
      provisioned_at  timestamptz
    );
    CREATE INDEX ON app.signups (lower(email), created_at DESC);
    GRANT SELECT, INSERT, UPDATE ON app.signups TO agentry_system;
    """)
    for key, name, tagline, audience, agents, pricing, sort, highlights in [
        ("starter", "Starter", "Every enquiry answered in a minute, on your website and WhatsApp",
         "Any small business with a website and a WhatsApp number", STARTER, plan("2999", "0", 1500, "49"), 10,
         ["Website chat that answers from your own pages", "WhatsApp replies in a minute, day and night", "New leads messaged within a minute",
          "Bookings into your calendar", "Approval mode first: you see every reply"]),
        ("clinic-growth", "Clinic growth", "Fuller diary, fewer no-shows, more reviews",
         "Clinics, salons, physios, diagnostics: anyone who runs on appointments", CLINIC, plan("6999", "0", 3000, "99"), 20,
         ["Everything in Starter", "Appointment reminders, confirmations and a waitlist", "Review requests and replies",
          "Monthly check of what ChatGPT says about you", "Results report every month"]),
    ]:
        op.execute(f"""INSERT INTO app.agent_packs (key, name, tagline, audience, agents, pricing, self_serve, sort, highlights)
          VALUES ('{key}', '{name}', '{tagline}', '{audience}', '{json.dumps([{"key": k, "default_on": on} for k, on in agents])}'::jsonb,
          '{json.dumps(pricing)}'::jsonb, true, {sort}, '{json.dumps(highlights)}'::jsonb) ON CONFLICT (key) DO NOTHING""")
    op.execute("""UPDATE app.agent_packs SET self_serve = true, sort = 30, highlights = '["Documents chased on WhatsApp", "Form 16, AIS and 26AS read and matched",
      "Every filing on one board", "Due dates with official extensions", "ITR, GST, TDS and audit tools"]'::jsonb WHERE key = 'ca-firm'""")


def downgrade() -> None:
    op.execute("""DROP TABLE app.signups; DELETE FROM app.agent_packs WHERE key IN ('starter', 'clinic-growth');
      ALTER TABLE app.agent_packs DROP COLUMN self_serve, DROP COLUMN sort, DROP COLUMN highlights;""")

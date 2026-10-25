"""Billing: pricing plans, outcomes (billable results with evidence), statements and lines, notification prefs.

Revision ID: 0007
"""
from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None

TENANT_TABLES = ["pricing_plans", "outcomes", "statements", "statement_lines"]


def upgrade() -> None:
    op.execute("""
    -- docs/PRICING.md §5: setup + retainer + included usage/overage + pay-per-result + revenue share, per client.
    CREATE TABLE app.pricing_plans (
      org_id          text PRIMARY KEY,
      currency        text NOT NULL,
      setup_fee       numeric(12,2) NOT NULL DEFAULT 0,
      setup_billed    boolean NOT NULL DEFAULT false,
      retainer        numeric(12,2) NOT NULL DEFAULT 0,
      included        jsonb NOT NULL DEFAULT '{}',   -- {"messages": 2000, "emails_triaged": 5000}
      overage         jsonb NOT NULL DEFAULT '{}',   -- {"messages": 1.0}   price per unit beyond included
      outcome_prices  jsonb NOT NULL DEFAULT '[]',   -- [{"outcome": "appointment_booked", "price": 300} | {"pct_of_customer_value": 0.15, "min": 500}]
      revenue_share   jsonb NOT NULL DEFAULT '{}',   -- {"basis": "overdue_only", "rate": 0.015, "cap": 25000, "window_days": 30, "strong_only": false}
      tax_rate        numeric(5,4) NOT NULL DEFAULT 0,   -- 0.18 GST for Indian clients
      pilot_until     date,
      starts_on       date NOT NULL DEFAULT current_date,
      term_months     int NOT NULL DEFAULT 1,
      updated_at      timestamptz NOT NULL DEFAULT now()
    );

    -- A billable (or excluded) result, recorded when it happens, with the evidence a client can check.
    CREATE TABLE app.outcomes (
      id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      org_id          text NOT NULL,
      kind            text NOT NULL CHECK (kind IN ('appointment_booked','amount_recovered')),
      source_ref      text NOT NULL,                 -- booking id / payment id: one outcome per source
      occurred_at     timestamptz NOT NULL,
      value           numeric(14,2) NOT NULL,        -- amount recovered, or the appointment's value
      strength        text NOT NULL DEFAULT 'strong' CHECK (strength IN ('strong','weak')),
      status          text NOT NULL DEFAULT 'billable' CHECK (status IN ('billable','excluded','cancelled')),
      exclusion_reason text,
      automation_key  text,
      evidence        jsonb NOT NULL DEFAULT '{}',
      statement_id    uuid,
      created_at      timestamptz NOT NULL DEFAULT now(),
      UNIQUE (org_id, kind, source_ref)
    );
    CREATE INDEX ON app.outcomes (org_id, occurred_at);

    CREATE SEQUENCE app.statement_number_seq START 1001;
    CREATE TABLE app.statements (
      id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      org_id        text NOT NULL,
      number        text NOT NULL UNIQUE,
      period_start  date NOT NULL,
      period_end    date NOT NULL,                  -- inclusive
      currency      text NOT NULL,
      status        text NOT NULL DEFAULT 'draft' CHECK (status IN ('draft','issued','finalized','paid','void')),
      subtotal      numeric(14,2) NOT NULL DEFAULT 0,
      tax           numeric(14,2) NOT NULL DEFAULT 0,
      total         numeric(14,2) NOT NULL DEFAULT 0,
      results       jsonb NOT NULL DEFAULT '{}',    -- summary for the results report (bookings, recovered, ROI)
      issued_at     timestamptz,
      dispute_until timestamptz,
      finalized_at  timestamptz,
      paid_at       timestamptz,
      payment_link  text,
      payment_ref   text,
      created_at    timestamptz NOT NULL DEFAULT now(),
      UNIQUE (org_id, period_start)
    );
    CREATE TABLE app.statement_lines (
      id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      org_id         text NOT NULL,
      statement_id   uuid NOT NULL REFERENCES app.statements(id) ON DELETE CASCADE,
      position       int NOT NULL,
      kind           text NOT NULL CHECK (kind IN ('setup','retainer','overage','outcome','commission','credit')),
      description    text NOT NULL,
      quantity       numeric(14,2) NOT NULL DEFAULT 1,
      unit_price     numeric(14,2) NOT NULL DEFAULT 0,
      amount         numeric(14,2) NOT NULL,
      evidence       jsonb NOT NULL DEFAULT '[]',   -- outcome ids / references behind this line
      disputed       boolean NOT NULL DEFAULT false,
      dispute_reason text,
      dispute_resolution text CHECK (dispute_resolution IN ('accepted','rejected'))
    );

    CREATE TABLE app.notification_preferences (
      user_id   text NOT NULL,
      org_id    text NOT NULL,
      prefs     jsonb NOT NULL DEFAULT '{}',        -- {"urgent": ["email"], "digest": ["email"], "billing": ["email"]}
      PRIMARY KEY (user_id, org_id)
    );
    ALTER TABLE app.notification_preferences ENABLE ROW LEVEL SECURITY;
    ALTER TABLE app.notification_preferences FORCE ROW LEVEL SECURITY;
    CREATE POLICY tenant_isolation ON app.notification_preferences
      USING (org_id = current_setting('app.org_id', true)) WITH CHECK (org_id = current_setting('app.org_id', true));
    GRANT SELECT, INSERT, UPDATE, DELETE ON app.notification_preferences TO agentry_app, agentry_system;
    GRANT USAGE ON SEQUENCE app.statement_number_seq TO agentry_app, agentry_system;
    """)
    for t in TENANT_TABLES:
        op.execute(f"""
        ALTER TABLE app.{t} ENABLE ROW LEVEL SECURITY;
        ALTER TABLE app.{t} FORCE ROW LEVEL SECURITY;
        CREATE POLICY tenant_isolation ON app.{t}
          USING (org_id = current_setting('app.org_id', true)) WITH CHECK (org_id = current_setting('app.org_id', true));
        GRANT SELECT, INSERT, UPDATE, DELETE ON app.{t} TO agentry_app, agentry_system;
        """)


def downgrade() -> None:
    op.execute("""DROP TABLE IF EXISTS app.notification_preferences, app.statement_lines, app.statements, app.outcomes,
      app.pricing_plans CASCADE; DROP SEQUENCE IF EXISTS app.statement_number_seq;""")

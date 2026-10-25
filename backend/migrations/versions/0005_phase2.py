"""Phase 2: lead engine identity + ownership, consent and suppression, sequences, invoices, payments, campaigns.

Revision ID: 0005
"""
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None

TENANT_TABLES = ["consents", "suppressions", "sequences", "sequence_enrollments", "invoices", "payments", "campaigns",
                 "lead_sources"]


def upgrade() -> None:
    op.execute("""
    -- Identity: normalised keys used to recognise the same person across channels and imports.
    ALTER TABLE app.contacts
      ADD COLUMN phone_e164 text,
      ADD COLUMN email_norm text,
      ADD COLUMN merged_into uuid REFERENCES app.contacts(id);
    UPDATE app.contacts SET email_norm = lower(trim(email)) WHERE email IS NOT NULL;
    CREATE INDEX contacts_phone_e164 ON app.contacts (org_id, phone_e164) WHERE merged_into IS NULL;
    CREATE INDEX contacts_email_norm ON app.contacts (org_id, email_norm) WHERE merged_into IS NULL;

    -- One voice: which automation currently owns the conversation with a lead (docs/automations/boring-machine.md §3.2).
    ALTER TABLE app.leads
      ADD COLUMN owner_automation text,
      ADD COLUMN owner_since timestamptz,
      ADD COLUMN last_touch_at timestamptz,
      ADD COLUMN touches int NOT NULL DEFAULT 0;

    CREATE TABLE app.consents (
      org_id     text NOT NULL,
      contact_id uuid NOT NULL REFERENCES app.contacts(id) ON DELETE CASCADE,
      channel    text NOT NULL CHECK (channel IN ('email','whatsapp','sms','voice')),
      status     text NOT NULL CHECK (status IN ('granted','revoked')),
      source     text,            -- e.g. 'import:whatsapp_optin', 'form', 'reply:stop'
      at         timestamptz NOT NULL DEFAULT now(),
      PRIMARY KEY (org_id, contact_id, channel)
    );

    -- Never contact these addresses again on that channel (opt-outs, bounces, complaints, DND).
    CREATE TABLE app.suppressions (
      org_id  text NOT NULL,
      channel text NOT NULL CHECK (channel IN ('email','whatsapp','sms','voice','all')),
      address text NOT NULL,      -- normalised email or E.164 phone
      reason  text NOT NULL CHECK (reason IN ('opt_out','bounce','complaint','dnd','manual')),
      at      timestamptz NOT NULL DEFAULT now(),
      PRIMARY KEY (org_id, channel, address)
    );

    -- Sequences: ordered steps ("day 7 after due: friendly email"), shared by invoices, reactivation and cold email.
    CREATE TABLE app.sequences (
      id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      org_id         text NOT NULL,
      key            text NOT NULL,
      name           text NOT NULL,
      automation_key text NOT NULL,
      steps          jsonb NOT NULL,      -- [{"offset_days": 7, "anchor": "due", "channels": ["email"], "tone": "friendly"}]
      created_at     timestamptz NOT NULL DEFAULT now(),
      UNIQUE (org_id, key)
    );
    CREATE TABLE app.sequence_enrollments (
      id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      org_id       text NOT NULL,
      sequence_id  uuid NOT NULL REFERENCES app.sequences(id),
      subject_type text NOT NULL CHECK (subject_type IN ('invoice','lead')),
      subject_id   uuid NOT NULL,
      contact_id   uuid REFERENCES app.contacts(id),
      status       text NOT NULL DEFAULT 'active' CHECK (status IN ('active','paused','completed','stopped')),
      last_step    int NOT NULL DEFAULT -1,  -- index of the last step sent
      next_run_at  timestamptz,
      paused_until timestamptz,
      stop_reason  text,
      log          jsonb NOT NULL DEFAULT '[]',
      created_at   timestamptz NOT NULL DEFAULT now(),
      updated_at   timestamptz NOT NULL DEFAULT now()
    );
    CREATE UNIQUE INDEX enrollment_one_active ON app.sequence_enrollments (sequence_id, subject_id) WHERE status IN ('active','paused');

    CREATE TABLE app.invoices (
      id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      org_id       text NOT NULL,
      contact_id   uuid REFERENCES app.contacts(id),
      number       text NOT NULL,
      currency     text NOT NULL,
      amount       numeric(14,2) NOT NULL CHECK (amount >= 0),
      amount_paid  numeric(14,2) NOT NULL DEFAULT 0,
      issued_on    date,
      due_on       date NOT NULL,
      status       text NOT NULL DEFAULT 'open' CHECK (status IN ('open','partially_paid','paid','disputed','written_off','void')),
      source       text NOT NULL,
      payment_link text,
      notes        text,
      metadata     jsonb NOT NULL DEFAULT '{}',
      created_at   timestamptz NOT NULL DEFAULT now(),
      updated_at   timestamptz NOT NULL DEFAULT now(),
      UNIQUE (org_id, number)
    );
    CREATE INDEX ON app.invoices (org_id, status, due_on);

    CREATE TABLE app.payments (
      id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      org_id      text NOT NULL,
      invoice_id  uuid REFERENCES app.invoices(id),
      amount      numeric(14,2) NOT NULL,
      currency    text NOT NULL,
      gateway     text NOT NULL,          -- razorpay | stripe | bank | manual | sync
      reference   text NOT NULL,          -- gateway payment id / UTR / cheque no.
      match       text NOT NULL CHECK (match IN ('strong','weak','manual','unmatched')),
      received_at timestamptz NOT NULL DEFAULT now(),
      raw         jsonb NOT NULL DEFAULT '{}',
      UNIQUE (org_id, gateway, reference)
    );

    -- Reactivation (and later cold email) campaigns: a list + a sequence + pacing.
    CREATE TABLE app.campaigns (
      id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      org_id       text NOT NULL,
      kind         text NOT NULL CHECK (kind IN ('reactivation','cold_email')),
      name         text NOT NULL,
      sequence_id  uuid NOT NULL REFERENCES app.sequences(id),
      status       text NOT NULL DEFAULT 'draft' CHECK (status IN ('draft','running','paused','completed')),
      per_hour     int NOT NULL DEFAULT 20 CHECK (per_hour BETWEEN 1 AND 500),
      stats        jsonb NOT NULL DEFAULT '{}',
      created_at   timestamptz NOT NULL DEFAULT now()
    );

    -- Public lead-capture endpoints (website forms, Meta lead ads via Zapier/Make, CRMs) for speed-to-lead.
    CREATE TABLE app.lead_sources (
      id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      org_id     text NOT NULL,
      name       text NOT NULL,
      key        text NOT NULL UNIQUE,   -- secret in the webhook URL
      created_at timestamptz NOT NULL DEFAULT now()
    );

    ALTER TABLE app.approvals DROP CONSTRAINT approvals_kind_check;
    ALTER TABLE app.approvals ADD CONSTRAINT approvals_kind_check
      CHECK (kind IN ('reply_draft','outbound_draft','escalation','dispute','low_confidence','handoff','payment_review'));
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
    op.execute("""
    DROP TABLE IF EXISTS app.lead_sources, app.campaigns, app.payments, app.invoices, app.sequence_enrollments,
      app.sequences, app.suppressions, app.consents CASCADE;
    ALTER TABLE app.leads DROP COLUMN owner_automation, DROP COLUMN owner_since, DROP COLUMN last_touch_at, DROP COLUMN touches;
    ALTER TABLE app.contacts DROP COLUMN phone_e164, DROP COLUMN email_norm, DROP COLUMN merged_into;
    """)

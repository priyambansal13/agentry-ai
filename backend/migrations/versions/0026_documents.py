"""Document AI + Bookkeeping (ROADMAP-V2 7.4, 9.5).

    documents   a photo or PDF a business sent (portal, WhatsApp, Telegram, email): typed fields extracted by the
                vision model with a confidence per field ({name: {value, confidence}}), the checks code ran (totals,
                GSTIN, date, duplicate), and a review state. Below the threshold a person checks it (a
                'document_review' card); only checked or confident documents are exported.
    approvals   new kind 'document_review'; bookkeeping cards follow the money permission like invoices (routing too).

Revision ID: 0026
"""
from alembic import op

revision = "0026"
down_revision = "0025"
branch_labels = None
depends_on = None

KINDS = "'reply_draft','outbound_draft','escalation','dispute','low_confidence','handoff','payment_review','callback'"


def upgrade() -> None:
    op.execute(f"""
    CREATE TABLE app.documents (
      id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      org_id          text NOT NULL,
      kind            text NOT NULL DEFAULT 'receipt' CHECK (kind IN ('receipt','bill','other')),
      source          text NOT NULL CHECK (source IN ('upload','whatsapp','telegram','email','sample')),
      filename        text,
      mime            text NOT NULL,
      bytes           int NOT NULL,
      sha256          text NOT NULL,
      file_path       text NOT NULL,
      status          text NOT NULL DEFAULT 'processing'
                      CHECK (status IN ('processing','needs_review','ready','rejected','failed')),
      fields          jsonb NOT NULL DEFAULT '{{}}',
      line_items      jsonb NOT NULL DEFAULT '[]',          -- [{{description, amount}}] as read: they must add up
      confidence      numeric(3,2),
      checks          jsonb NOT NULL DEFAULT '[]',
      duplicate_of    uuid REFERENCES app.documents(id),
      contact_id      uuid REFERENCES app.contacts(id),
      conversation_id uuid,
      automation_key  text,
      error           text,
      created_by      text,
      created_at      timestamptz NOT NULL DEFAULT now(),
      reviewed_by     text,
      reviewed_at     timestamptz,
      exported_at     timestamptz
    );
    CREATE INDEX ON app.documents (org_id, status, created_at DESC);
    CREATE INDEX ON app.documents (org_id, sha256);
    ALTER TABLE app.documents ENABLE ROW LEVEL SECURITY;
    ALTER TABLE app.documents FORCE ROW LEVEL SECURITY;
    CREATE POLICY tenant_isolation ON app.documents
      USING (org_id = current_setting('app.org_id', true)) WITH CHECK (org_id = current_setting('app.org_id', true));
    GRANT SELECT, INSERT, UPDATE, DELETE ON app.documents TO agentry_app, agentry_system;

    ALTER TABLE app.approvals DROP CONSTRAINT approvals_kind_check;
    ALTER TABLE app.approvals ADD CONSTRAINT approvals_kind_check CHECK (kind IN ({KINDS},'document_review'));

    CREATE OR REPLACE FUNCTION app.card_assignee(p jsonb, conv uuid, automation text) RETURNS text LANGUAGE sql STABLE AS $$
      SELECT coalesce(
        (SELECT assign_to FROM app.card_routing WHERE scope = 'contact' AND key = app.card_contact(p, conv)::text
           AND (CASE WHEN automation IN ('invoice_follow_up', 'bookkeeping') THEN 'invoice' ELSE 'conversation' END) = ANY (resources)),
        (SELECT assign_to FROM app.card_routing WHERE scope = 'automation' AND key = automation))
    $$;
    """)


def downgrade() -> None:
    op.execute(f"""
    CREATE OR REPLACE FUNCTION app.card_assignee(p jsonb, conv uuid, automation text) RETURNS text LANGUAGE sql STABLE AS $$
      SELECT coalesce(
        (SELECT assign_to FROM app.card_routing WHERE scope = 'contact' AND key = app.card_contact(p, conv)::text
           AND (CASE WHEN automation = 'invoice_follow_up' THEN 'invoice' ELSE 'conversation' END) = ANY (resources)),
        (SELECT assign_to FROM app.card_routing WHERE scope = 'automation' AND key = automation))
    $$;
    DELETE FROM app.approvals WHERE kind = 'document_review';
    ALTER TABLE app.approvals DROP CONSTRAINT approvals_kind_check;
    ALTER TABLE app.approvals ADD CONSTRAINT approvals_kind_check CHECK (kind IN ({KINDS}));
    DROP TABLE app.documents;
    """)

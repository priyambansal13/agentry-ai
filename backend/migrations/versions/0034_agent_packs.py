"""Packs (docs/PACKS.md): sellable bundles of agents. A client can have one pack (tailored per client) plus standalone
add-ons; each automation instance records which way it came.

Revision ID: 0034
"""
import json

from alembic import op

revision = "0034"
down_revision = "0033"
branch_labels = None
depends_on = None

CA_AGENTS = [
    ("inbox_triage", True), ("whatsapp_assistant", True), ("ca_document_chaser", True), ("ca_tax_docs_reader", True),
    ("ca_filing_tracker", True), ("ca_compliance_calendar", True), ("invoice_follow_up", True), ("bookkeeping", True),
    ("ca_itr_prep", False), ("ca_capital_gains", False), ("ca_bank_classifier", False), ("ca_notice_handler", False),
    ("ca_gst_reconciliation", False), ("ca_tds_returns", False), ("ca_tax_audit", False), ("recurring_books", False),
    ("excel_desk", False), ("appointment_concierge", False), ("ai_receptionist", False), ("website_chat", False),
]
CA_PRICING = {
    "INR": {"currency": "INR", "setup_fee": "15000", "retainer": "14999", "included": {"messages": 3000, "emails_triaged": 1500},
            "overage": {"messages": "1.50", "emails_triaged": "2.00"}, "tax_rate": 0.18},
    "USD": {"currency": "USD", "setup_fee": "299", "retainer": "299", "included": {"messages": 3000, "emails_triaged": 1500},
            "overage": {"messages": "0.03", "emails_triaged": "0.04"}, "tax_rate": 0},
}


def upgrade() -> None:
    op.execute("""
    -- Platform data (not tenant-scoped): edited by Agentry staff in HQ, readable by the portal.
    CREATE TABLE app.agent_packs (
      key         text PRIMARY KEY CHECK (key ~ '^[a-z0-9][a-z0-9-]{1,40}$'),
      name        text NOT NULL,
      tagline     text NOT NULL DEFAULT '',
      audience    text NOT NULL DEFAULT '',
      agents      jsonb NOT NULL DEFAULT '[]',  -- [{"key": ..., "default_on": bool}] in display order
      pricing     jsonb NOT NULL DEFAULT '{}',  -- {"INR": PricingPlan, "USD": ...}
      active      boolean NOT NULL DEFAULT true,
      created_at  timestamptz NOT NULL DEFAULT now(),
      updated_at  timestamptz NOT NULL DEFAULT now()
    );
    GRANT SELECT ON app.agent_packs TO agentry_app;
    GRANT SELECT, INSERT, UPDATE, DELETE ON app.agent_packs TO agentry_system;

    ALTER TABLE app.org_settings ADD COLUMN agent_pack text REFERENCES app.agent_packs(key) ON UPDATE CASCADE,
      ADD COLUMN agent_pack_agents jsonb NOT NULL DEFAULT '[]';
    ALTER TABLE app.automation_instances ADD COLUMN source text NOT NULL DEFAULT 'standalone'
      CHECK (source IN ('pack','standalone'));
    """)
    agents = json.dumps([{"key": k, "default_on": on} for k, on in CA_AGENTS])
    op.execute(f"""INSERT INTO app.agent_packs (key, name, tagline, audience, agents, pricing) VALUES ('ca-firm', 'CA Firm',
      'Documents chased, AIS matched, every filing on one board',
      'Chartered accountants, tax consultants, compliance and small law firms',
      '{agents}'::jsonb, '{json.dumps(CA_PRICING)}'::jsonb)""")


def downgrade() -> None:
    op.execute("""
    ALTER TABLE app.automation_instances DROP COLUMN source;
    ALTER TABLE app.org_settings DROP COLUMN agent_pack, DROP COLUMN agent_pack_agents;
    DROP TABLE app.agent_packs;
    """)

"""CA client portal (docs/PLAN-COMMERCIAL-2026-11.md #3): private links for a firm's clients, the firm's portal settings,
and active portal clients as a billable usage line.

Revision ID: 0059
"""
from alembic import op

revision = "0059"
down_revision = "0058"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
    ALTER TABLE app.org_settings ADD COLUMN client_portal jsonb NOT NULL DEFAULT '{}';  -- {enabled, title, color, logo_url, welcome}
    CREATE TABLE app.ca_portal_links (
      id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      org_id        text NOT NULL,
      client_id     uuid NOT NULL REFERENCES app.ca_clients(id) ON DELETE CASCADE,
      token_hash    text NOT NULL UNIQUE,
      created_by    text,
      created_at    timestamptz NOT NULL DEFAULT now(),
      expires_at    timestamptz NOT NULL DEFAULT now() + interval '90 days',
      revoked_at    timestamptz,
      last_used_at  timestamptz,
      uses          int NOT NULL DEFAULT 0
    );
    CREATE INDEX ON app.ca_portal_links (org_id, client_id);
    ALTER TABLE app.ca_portal_links ENABLE ROW LEVEL SECURITY;
    ALTER TABLE app.ca_portal_links FORCE ROW LEVEL SECURITY;
    CREATE POLICY tenant_isolation ON app.ca_portal_links USING (org_id = current_setting('app.org_id', true))
      WITH CHECK (org_id = current_setting('app.org_id', true));
    GRANT SELECT, INSERT, UPDATE, DELETE ON app.ca_portal_links TO agentry_app, agentry_system;
    ALTER TABLE app.ca_files DROP CONSTRAINT ca_files_source_check;
    ALTER TABLE app.ca_files ADD CONSTRAINT ca_files_source_check CHECK (source IN ('portal','whatsapp','telegram','email','client_portal'));
    -- the CA plan: ₹99 / $2 per client who used the portal in the month
    UPDATE app.agent_packs SET pricing = jsonb_set(jsonb_set(pricing, '{INR,overage,portal_clients}', '"99"'), '{USD,overage,portal_clients}', '"2"')
      WHERE key = 'ca-firm';
    """)


def downgrade() -> None:
    op.execute("""DROP TABLE app.ca_portal_links;
      ALTER TABLE app.ca_files DROP CONSTRAINT ca_files_source_check;
      ALTER TABLE app.ca_files ADD CONSTRAINT ca_files_source_check CHECK (source IN ('portal','whatsapp','telegram','email')); ALTER TABLE app.org_settings DROP COLUMN client_portal;
      UPDATE app.agent_packs SET pricing = (pricing #- '{INR,overage,portal_clients}') #- '{USD,overage,portal_clients}' WHERE key = 'ca-firm';""")

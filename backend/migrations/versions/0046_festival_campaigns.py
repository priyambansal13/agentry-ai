"""Festival & seasonal campaigns (ROADMAP-V3 B3): a plan per festival with posts, a WhatsApp message and a timeline.

Revision ID: 0046
"""
from alembic import op

revision = "0046"
down_revision = "0045"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
    CREATE TABLE app.festival_plans (
      id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      org_id      text NOT NULL,
      festival    text NOT NULL,
      name        text NOT NULL,
      on_date     date NOT NULL,
      plan        jsonb NOT NULL,
      checks      jsonb NOT NULL DEFAULT '[]',
      status      text NOT NULL DEFAULT 'draft' CHECK (status IN ('draft','needs_attention','approved','done','skipped')),
      created_at  timestamptz NOT NULL DEFAULT now(),
      updated_at  timestamptz NOT NULL DEFAULT now(),
      UNIQUE (org_id, festival, on_date)
    );
    ALTER TABLE app.festival_plans ENABLE ROW LEVEL SECURITY;
    ALTER TABLE app.festival_plans FORCE ROW LEVEL SECURITY;
    CREATE POLICY tenant_isolation ON app.festival_plans USING (org_id = current_setting('app.org_id', true))
      WITH CHECK (org_id = current_setting('app.org_id', true));
    GRANT SELECT, INSERT, UPDATE, DELETE ON app.festival_plans TO agentry_app, agentry_system;
    """)


def downgrade() -> None:
    op.execute("DROP TABLE app.festival_plans;")

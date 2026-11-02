"""Business copilot (ROADMAP-V3 C1): plans of actions a person confirms with one tap.

Revision ID: 0049
"""
from alembic import op

revision = "0049"
down_revision = "0048"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
    CREATE TABLE app.copilot_plans (
      id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      org_id      text NOT NULL,
      user_id     text,
      question    text NOT NULL,
      steps       jsonb NOT NULL,
      status      text NOT NULL DEFAULT 'proposed' CHECK (status IN ('proposed','running','done','cancelled')),
      results     jsonb,
      created_at  timestamptz NOT NULL DEFAULT now(),
      ran_at      timestamptz
    );
    ALTER TABLE app.copilot_plans ENABLE ROW LEVEL SECURITY;
    ALTER TABLE app.copilot_plans FORCE ROW LEVEL SECURITY;
    CREATE POLICY tenant_isolation ON app.copilot_plans USING (org_id = current_setting('app.org_id', true))
      WITH CHECK (org_id = current_setting('app.org_id', true));
    GRANT SELECT, INSERT, UPDATE, DELETE ON app.copilot_plans TO agentry_app, agentry_system;
    """)


def downgrade() -> None:
    op.execute("DROP TABLE app.copilot_plans;")

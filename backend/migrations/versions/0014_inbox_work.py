"""Inbox triage, day-to-day work: snooze and assign Needs-you cards, saved replies, label corrections.

Revision ID: 0014
"""
from alembic import op

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None

TENANT_TABLES = ["reply_templates", "label_corrections"]


def upgrade() -> None:
    op.execute("""
    ALTER TABLE app.approvals
      ADD COLUMN snoozed_until timestamptz,
      ADD COLUMN assigned_to text,                    -- user id of the person who should handle it
      ADD COLUMN assigned_by text;
    CREATE TABLE app.reply_templates (
      id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      org_id      text NOT NULL,
      title       text NOT NULL,
      body        text NOT NULL,
      created_by  text,
      created_at  timestamptz NOT NULL DEFAULT now(),
      updated_at  timestamptz NOT NULL DEFAULT now(),
      UNIQUE (org_id, title)
    );
    CREATE TABLE app.label_corrections (
      id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      org_id         text NOT NULL,
      conversation_id uuid NOT NULL,
      sender         text NOT NULL,                  -- lower-cased address
      sender_domain  text NOT NULL,
      subject        text,
      from_category  text NOT NULL,
      to_category    text NOT NULL,
      corrected_by   text,
      created_at     timestamptz NOT NULL DEFAULT now()
    );
    CREATE INDEX ON app.label_corrections (org_id, sender);
    CREATE INDEX ON app.label_corrections (org_id, sender_domain);
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
    DROP TABLE app.label_corrections; DROP TABLE app.reply_templates;
    ALTER TABLE app.approvals DROP COLUMN snoozed_until, DROP COLUMN assigned_to, DROP COLUMN assigned_by;
    """)

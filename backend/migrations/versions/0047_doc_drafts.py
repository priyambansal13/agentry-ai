"""SOP & proposal drafter (ROADMAP-V3 B4, v2 11.5): procedures with a flowchart, client proposals, checklists.

Revision ID: 0047
"""
from alembic import op

revision = "0047"
down_revision = "0046"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
    CREATE TABLE app.doc_drafts (
      id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      org_id      text NOT NULL,
      kind        text NOT NULL CHECK (kind IN ('sop','proposal','checklist')),
      title       text NOT NULL,
      brief       jsonb NOT NULL,
      content     text NOT NULL,
      diagram     text,
      checks      jsonb NOT NULL DEFAULT '[]',
      status      text NOT NULL DEFAULT 'draft' CHECK (status IN ('draft','needs_attention','final')),
      created_by  text,
      created_at  timestamptz NOT NULL DEFAULT now(),
      updated_at  timestamptz NOT NULL DEFAULT now()
    );
    ALTER TABLE app.doc_drafts ENABLE ROW LEVEL SECURITY;
    ALTER TABLE app.doc_drafts FORCE ROW LEVEL SECURITY;
    CREATE POLICY tenant_isolation ON app.doc_drafts USING (org_id = current_setting('app.org_id', true))
      WITH CHECK (org_id = current_setting('app.org_id', true));
    GRANT SELECT, INSERT, UPDATE, DELETE ON app.doc_drafts TO agentry_app, agentry_system;
    """)


def downgrade() -> None:
    op.execute("DROP TABLE app.doc_drafts;")

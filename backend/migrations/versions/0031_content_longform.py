"""Content v2 (ROADMAP-V2 8.3): an SEO blog article and an email newsletter from each recording.

    content_longform   kind blog | newsletter, title (or subject), summary (meta description / preheader), body in
                       Markdown, the checks it passed or failed (quotes word for word, numbers in the recording),
                       review state, when it was exported

Revision ID: 0031
"""
from alembic import op

revision = "0031"
down_revision = "0030"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
    CREATE TABLE app.content_longform (
      id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      org_id       text NOT NULL,
      source_id    uuid NOT NULL REFERENCES app.content_sources(id) ON DELETE CASCADE,
      kind         text NOT NULL CHECK (kind IN ('blog','newsletter')),
      status       text NOT NULL DEFAULT 'writing' CHECK (status IN ('writing','ready','needs_attention','approved','failed')),
      title        text,
      summary      text,
      slug         text,
      body         text,
      problems     jsonb NOT NULL DEFAULT '[]',
      error        text,
      approved_by  text,
      approved_at  timestamptz,
      exported_at  timestamptz,
      created_at   timestamptz NOT NULL DEFAULT now(),
      updated_at   timestamptz NOT NULL DEFAULT now(),
      UNIQUE (source_id, kind)
    );
    ALTER TABLE app.content_longform ENABLE ROW LEVEL SECURITY;
    ALTER TABLE app.content_longform FORCE ROW LEVEL SECURITY;
    CREATE POLICY tenant_isolation ON app.content_longform
      USING (org_id = current_setting('app.org_id', true)) WITH CHECK (org_id = current_setting('app.org_id', true));
    GRANT SELECT, INSERT, UPDATE, DELETE ON app.content_longform TO agentry_app, agentry_system;
    """)


def downgrade() -> None:
    op.execute("DROP TABLE app.content_longform;")

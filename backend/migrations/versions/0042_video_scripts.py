"""Topic -> script (ROADMAP-V3 A6, v2 8.4): timed scripts for the owner to film, from the AI video studio.

Revision ID: 0042
"""
from alembic import op

revision = "0042"
down_revision = "0041"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
    CREATE TABLE app.video_scripts (
      id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      org_id      text NOT NULL,
      topic       text NOT NULL,
      language    text NOT NULL DEFAULT 'English',
      script      jsonb NOT NULL,       -- hook, beats [{at, say, show, on_screen}], cta, caption, hashtags, seconds
      status      text NOT NULL DEFAULT 'new' CHECK (status IN ('new','filmed','used','dropped')),
      created_by  text,
      created_at  timestamptz NOT NULL DEFAULT now()
    );
    CREATE INDEX ON app.video_scripts (org_id, created_at DESC);
    ALTER TABLE app.video_scripts ENABLE ROW LEVEL SECURITY;
    ALTER TABLE app.video_scripts FORCE ROW LEVEL SECURITY;
    CREATE POLICY tenant_isolation ON app.video_scripts USING (org_id = current_setting('app.org_id', true))
      WITH CHECK (org_id = current_setting('app.org_id', true));
    GRANT SELECT, INSERT, UPDATE, DELETE ON app.video_scripts TO agentry_app, agentry_system;
    """)


def downgrade() -> None:
    op.execute("DROP TABLE app.video_scripts;")

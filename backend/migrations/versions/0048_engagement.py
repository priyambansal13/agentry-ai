"""Engagement loop (ROADMAP-V3 B5, v2 8.6): likes, comments, reach and views at +24 h and +7 days for what was published.

Revision ID: 0048
"""
from alembic import op

revision = "0048"
down_revision = "0047"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
    ALTER TABLE app.content_posts ADD COLUMN publish_id text;   -- the platform's id for the post (Instagram media id…)
    CREATE TABLE app.post_metrics (
      id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      org_id      text NOT NULL,
      kind        text NOT NULL CHECK (kind IN ('post','video')),
      ref_id      uuid NOT NULL,
      platform    text NOT NULL,
      at_hours    int NOT NULL CHECK (at_hours IN (24, 168)),
      views       int, likes int, comments int, shares int, saves int, reach int,
      score       numeric(12,2) NOT NULL DEFAULT 0,
      fetched_at  timestamptz NOT NULL DEFAULT now(),
      UNIQUE (org_id, kind, ref_id, at_hours)
    );
    ALTER TABLE app.post_metrics ENABLE ROW LEVEL SECURITY;
    ALTER TABLE app.post_metrics FORCE ROW LEVEL SECURITY;
    CREATE POLICY tenant_isolation ON app.post_metrics USING (org_id = current_setting('app.org_id', true))
      WITH CHECK (org_id = current_setting('app.org_id', true));
    GRANT SELECT, INSERT, UPDATE, DELETE ON app.post_metrics TO agentry_app, agentry_system;
    """)


def downgrade() -> None:
    op.execute("DROP TABLE app.post_metrics; ALTER TABLE app.content_posts DROP COLUMN publish_id;")

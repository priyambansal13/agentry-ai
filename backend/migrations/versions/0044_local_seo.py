"""Local SEO (ROADMAP-V3 B1, v2 10.2): website audits and location-targeted articles.

Revision ID: 0044
"""
from alembic import op

revision = "0044"
down_revision = "0043"
branch_labels = None
depends_on = None

TABLES = ["seo_audits", "seo_articles"]


def upgrade() -> None:
    op.execute("""
    CREATE TABLE app.seo_audits (
      id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      org_id      text NOT NULL,
      url         text NOT NULL,
      score       int NOT NULL,
      result      jsonb NOT NULL,
      created_at  timestamptz NOT NULL DEFAULT now()
    );
    CREATE INDEX ON app.seo_audits (org_id, created_at DESC);
    CREATE TABLE app.seo_articles (
      id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      org_id      text NOT NULL,
      topic       text NOT NULL,
      city        text,
      title       text NOT NULL,
      meta        text,
      slug        text NOT NULL,
      body        text NOT NULL,
      faqs        jsonb NOT NULL DEFAULT '[]',
      checks      jsonb NOT NULL DEFAULT '[]',
      status      text NOT NULL DEFAULT 'draft' CHECK (status IN ('draft','needs_attention','approved','published')),
      created_at  timestamptz NOT NULL DEFAULT now(),
      updated_at  timestamptz NOT NULL DEFAULT now()
    );
    CREATE INDEX ON app.seo_articles (org_id, created_at DESC);
    """)
    for t in TABLES:
        op.execute(f"""
        ALTER TABLE app.{t} ENABLE ROW LEVEL SECURITY;
        ALTER TABLE app.{t} FORCE ROW LEVEL SECURITY;
        CREATE POLICY tenant_isolation ON app.{t} USING (org_id = current_setting('app.org_id', true))
          WITH CHECK (org_id = current_setting('app.org_id', true));
        GRANT SELECT, INSERT, UPDATE, DELETE ON app.{t} TO agentry_app, agentry_system;
        """)


def downgrade() -> None:
    op.execute("DROP TABLE app.seo_articles; DROP TABLE app.seo_audits;")

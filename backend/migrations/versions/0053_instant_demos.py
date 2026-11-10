"""Instant demos on the website: a visitor's own AI assistant, answering from their website's pages for 24 hours.

Revision ID: 0053
"""
from alembic import op

revision = "0053"
down_revision = "0052"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
    CREATE TABLE app.instant_demos (
      id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      url         text NOT NULL,
      domain      text NOT NULL,
      name        text NOT NULL,
      brand       jsonb NOT NULL DEFAULT '{}',
      pages       jsonb NOT NULL DEFAULT '[]',     -- [{"url", "title", "text"}] read from the site (public pages only)
      ip_hash     text,
      source      text,
      messages    int NOT NULL DEFAULT 0,
      cost_usd    numeric(10,4) NOT NULL DEFAULT 0,
      created_at  timestamptz NOT NULL DEFAULT now(),
      expires_at  timestamptz NOT NULL DEFAULT now() + interval '24 hours'
    );
    CREATE INDEX ON app.instant_demos (created_at DESC);
    GRANT SELECT, INSERT, UPDATE, DELETE ON app.instant_demos TO agentry_system;
    """)


def downgrade() -> None:
    op.execute("DROP TABLE app.instant_demos;")

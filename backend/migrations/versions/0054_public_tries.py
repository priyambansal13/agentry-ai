"""The website's try-it boxes on agent pages (agentry/playground.py): one row per AI-backed try, for the daily budget.

Revision ID: 0054
"""
from alembic import op

revision = "0054"
down_revision = "0053"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
    CREATE TABLE app.public_tries (
      id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      kind        text NOT NULL,
      ip_hash     text,
      cost_usd    numeric(10,4) NOT NULL DEFAULT 0,
      created_at  timestamptz NOT NULL DEFAULT now()
    );
    CREATE INDEX ON app.public_tries (created_at DESC);
    GRANT SELECT, INSERT, UPDATE, DELETE ON app.public_tries TO agentry_system;
    """)


def downgrade() -> None:
    op.execute("DROP TABLE app.public_tries;")

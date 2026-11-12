"""Changes to the official figures the agents use (official_rules.py): tax slabs, TDS rates, audit limits, festival dates.

Revision ID: 0056
"""
from alembic import op

revision = "0056"
down_revision = "0055"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
    CREATE TABLE app.rule_updates (
      id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      key          text NOT NULL,                 -- official_rules.RULES key, e.g. tds.194J(b).threshold
      old_value    jsonb,                         -- the value it replaces (null: a new one, e.g. next year's festival date)
      new_value    jsonb NOT NULL,
      applies_from text,                          -- e.g. "FY 2026-27", as the source says
      title        text NOT NULL,
      source       text NOT NULL,
      source_url   text,
      quote        text,
      status       text NOT NULL DEFAULT 'proposed' CHECK (status IN ('proposed','active','rejected','withdrawn')),
      found_by     text NOT NULL DEFAULT 'staff' CHECK (found_by IN ('staff','sync')),
      checks       jsonb NOT NULL DEFAULT '{}',
      decided_by   text,
      decided_at   timestamptz,
      created_at   timestamptz NOT NULL DEFAULT now()
    );
    CREATE INDEX ON app.rule_updates (status, key);
    GRANT SELECT, INSERT, UPDATE, DELETE ON app.rule_updates TO agentry_system;
    GRANT SELECT ON app.rule_updates TO agentry_app;
    """)


def downgrade() -> None:
    op.execute("DROP TABLE app.rule_updates;")

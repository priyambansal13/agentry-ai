"""Official due-date changes (extensions) shared by every CA firm, and the checks of official sources that find them.

Revision ID: 0055
"""
from alembic import op

revision = "0055"
down_revision = "0054"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
    -- one row per change to a statutory due date (e.g. ITR AY 2026-27 non-audit: 31 Jul -> 15 Sep); not per firm
    CREATE TABLE app.due_date_updates (
      id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      kind         text NOT NULL,                 -- filing kind (ca core KINDS)
      period       text NOT NULL,                 -- the calendar's period label: "AY 2026-27", "2026-10", "Q2 FY 2026-27"
      original_on  date,                          -- the date it replaces (tells audit / non-audit ITR apart); null = any
      due_on       date NOT NULL,                 -- the new date
      title        text NOT NULL,
      source       text NOT NULL,                 -- notification / circular / press release, as named by the department
      source_url   text,
      quote        text,                          -- the words in the source that give the new date
      status       text NOT NULL DEFAULT 'proposed' CHECK (status IN ('proposed','active','rejected','withdrawn')),
      found_by     text NOT NULL DEFAULT 'staff' CHECK (found_by IN ('staff','sync')),
      checks       jsonb NOT NULL DEFAULT '{}',   -- {official, opened, date_on_page, note}
      cards        int NOT NULL DEFAULT 0,        -- board cards moved when it was applied
      decided_by   text,
      decided_at   timestamptz,
      created_at   timestamptz NOT NULL DEFAULT now()
    );
    CREATE INDEX ON app.due_date_updates (status, kind, period);
    -- each check of the official sources (daily, or a "check now" from HQ or a firm)
    CREATE TABLE app.due_date_syncs (
      id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      trigger      text NOT NULL,                 -- daily / staff / firm
      org_id       text,                          -- the firm that asked, if any
      status       text NOT NULL DEFAULT 'running' CHECK (status IN ('running','done','failed')),
      found        int NOT NULL DEFAULT 0,
      proposed     int NOT NULL DEFAULT 0,
      sources      jsonb NOT NULL DEFAULT '[]',   -- [{name, url, ok, note}]
      error        text,
      cost_usd     numeric(10,4) NOT NULL DEFAULT 0,
      started_at   timestamptz NOT NULL DEFAULT now(),
      finished_at  timestamptz
    );
    CREATE INDEX ON app.due_date_syncs (started_at DESC);
    GRANT SELECT, INSERT, UPDATE, DELETE ON app.due_date_updates, app.due_date_syncs TO agentry_system;
    GRANT SELECT ON app.due_date_updates, app.due_date_syncs TO agentry_app;  -- firms read them (no tenant data in them)
    """)


def downgrade() -> None:
    op.execute("DROP TABLE app.due_date_syncs; DROP TABLE app.due_date_updates;")

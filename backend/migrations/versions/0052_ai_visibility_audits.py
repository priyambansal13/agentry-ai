"""AI visibility agent (monthly: do AI assistants name the business?) and the public website audit.

Revision ID: 0052
"""
from alembic import op

revision = "0052"
down_revision = "0051"
branch_labels = None
depends_on = None

TENANT = ["ai_vis_runs", "ai_vis_answers"]


def upgrade() -> None:
    op.execute("""
    CREATE TABLE app.ai_vis_runs (
      id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      org_id       text NOT NULL,
      trigger      text NOT NULL DEFAULT 'manual' CHECK (trigger IN ('monthly','manual')),
      status       text NOT NULL DEFAULT 'queued' CHECK (status IN ('queued','running','done','failed')),
      setup        jsonb NOT NULL DEFAULT '{}',     -- what was asked: business, competitors, questions, engines
      score        jsonb,                           -- ai_search.score(...) + fixes
      cost_usd     numeric(10,4) NOT NULL DEFAULT 0,
      mock         boolean NOT NULL DEFAULT false,
      error        text,
      created_by   text,
      created_at   timestamptz NOT NULL DEFAULT now(),
      finished_at  timestamptz
    );
    CREATE INDEX ON app.ai_vis_runs (org_id, created_at DESC);
    CREATE TABLE app.ai_vis_answers (
      id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      org_id       text NOT NULL,
      run_id       uuid NOT NULL REFERENCES app.ai_vis_runs(id) ON DELETE CASCADE,
      engine       text NOT NULL,
      question     text NOT NULL,
      repeat       int NOT NULL DEFAULT 0,
      answer       text NOT NULL DEFAULT '',
      citations    jsonb NOT NULL DEFAULT '[]',
      named        jsonb NOT NULL DEFAULT '[]',     -- [{"name", "position", "said", "who": "me" | competitor | null}]
      me_position  int,
      error        text,
      created_at   timestamptz NOT NULL DEFAULT now()
    );
    CREATE INDEX ON app.ai_vis_answers (run_id);

    -- public website audits (no org: anyone on the website); read back by id only
    CREATE TABLE app.site_audits (
      id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      url           text NOT NULL,
      domain        text NOT NULL,
      city          text NOT NULL,
      service       text NOT NULL,
      status        text NOT NULL DEFAULT 'queued' CHECK (status IN ('queued','running','done','failed')),
      score         int,
      result        jsonb,
      cost_usd      numeric(10,4) NOT NULL DEFAULT 0,
      ip_hash       text,
      source        text,                           -- utm / gclid summary from the page
      name          text,
      email         text,
      phone         text,
      demo_request_id uuid,
      report_sent_at timestamptz,
      error         text,
      created_at    timestamptz NOT NULL DEFAULT now(),
      finished_at   timestamptz
    );
    CREATE INDEX ON app.site_audits (domain, created_at DESC);
    CREATE INDEX ON app.site_audits (created_at DESC);

    -- public rate limits shared by every API process (key = what + ip hash)
    CREATE TABLE app.public_hits (
      key  text NOT NULL,
      at   timestamptz NOT NULL DEFAULT now()
    );
    CREATE INDEX ON app.public_hits (key, at DESC);
    GRANT SELECT, INSERT, UPDATE, DELETE ON app.site_audits, app.public_hits TO agentry_system;
    """)
    for t in TENANT:
        op.execute(f"""
        ALTER TABLE app.{t} ENABLE ROW LEVEL SECURITY;
        ALTER TABLE app.{t} FORCE ROW LEVEL SECURITY;
        CREATE POLICY tenant_isolation ON app.{t} USING (org_id = current_setting('app.org_id', true))
          WITH CHECK (org_id = current_setting('app.org_id', true));
        GRANT SELECT, INSERT, UPDATE, DELETE ON app.{t} TO agentry_app, agentry_system;
        """)


def downgrade() -> None:
    op.execute("DROP TABLE app.ai_vis_answers; DROP TABLE app.ai_vis_runs; DROP TABLE app.site_audits; DROP TABLE app.public_hits;")

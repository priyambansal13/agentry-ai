"""Agent runs (ROADMAP-V2 §2.5): every piece of agent work is a run, with its steps, model calls, cost and outcome.

A run is one unit a person would recognise: an email triaged, a chat turn answered, a recording turned into posts, a
prospect list built, a reminder written. Long jobs that span several workflow steps share one run through `key`
(e.g. "content:<source id>"). Model calls made inside a run carry its id, so cost and tokens add up per run, per
agent and per client.

Revision ID: 0022
"""
from alembic import op

revision = "0022"
down_revision = "0021"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
    CREATE TABLE app.agent_runs (
      id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      org_id       text NOT NULL,
      agent        text NOT NULL,                   -- automation key, e.g. inbox_triage
      kind         text NOT NULL,                   -- e.g. triage.email, chat.turn, content.source
      key          text,                            -- shared by the steps of one long job
      subject_type text,
      subject_id   text,
      status       text NOT NULL DEFAULT 'running' CHECK (status IN ('running','ok','failed')),
      steps        jsonb NOT NULL DEFAULT '[]',     -- [{name, at, ms, detail}]
      error        text,
      model_calls  int NOT NULL DEFAULT 0,
      input_tokens int NOT NULL DEFAULT 0,
      output_tokens int NOT NULL DEFAULT 0,
      cost_usd     numeric(12, 6) NOT NULL DEFAULT 0,
      started_at   timestamptz NOT NULL DEFAULT now(),
      ended_at     timestamptz,
      UNIQUE (org_id, key)
    );
    CREATE INDEX ON app.agent_runs (org_id, agent, started_at DESC);
    ALTER TABLE app.agent_runs ENABLE ROW LEVEL SECURITY;
    ALTER TABLE app.agent_runs FORCE ROW LEVEL SECURITY;
    CREATE POLICY tenant_isolation ON app.agent_runs
      USING (org_id = current_setting('app.org_id', true)) WITH CHECK (org_id = current_setting('app.org_id', true));
    GRANT SELECT, INSERT, UPDATE, DELETE ON app.agent_runs TO agentry_app, agentry_system;

    ALTER TABLE app.llm_calls ADD COLUMN run_id uuid;
    CREATE INDEX ON app.llm_calls (run_id) WHERE run_id IS NOT NULL;
    """)


def downgrade() -> None:
    op.execute("ALTER TABLE app.llm_calls DROP COLUMN run_id; DROP TABLE app.agent_runs;")

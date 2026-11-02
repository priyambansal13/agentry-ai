"""Hiring assistant (ROADMAP-V3 A5): open roles and the candidates who apply, each scored with reasons.

Revision ID: 0041
"""
from alembic import op

revision = "0041"
down_revision = "0040"
branch_labels = None
depends_on = None

TABLES = ["jobs", "candidates"]


def upgrade() -> None:
    op.execute("""
    CREATE TABLE app.jobs (
      id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      org_id       text NOT NULL,
      token        text NOT NULL UNIQUE,      -- the public apply link
      title        text NOT NULL,
      description  text NOT NULL,
      must_have    jsonb NOT NULL DEFAULT '[]',
      location     text,
      kind         text NOT NULL DEFAULT 'full_time',
      status       text NOT NULL DEFAULT 'open' CHECK (status IN ('open','paused','closed')),
      post         text,                      -- a job post written for job boards
      created_by   text,
      created_at   timestamptz NOT NULL DEFAULT now()
    );
    CREATE TABLE app.candidates (
      id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      org_id       text NOT NULL,
      job_id       uuid NOT NULL REFERENCES app.jobs(id) ON DELETE CASCADE,
      contact_id   uuid REFERENCES app.contacts(id) ON DELETE SET NULL,
      name         text,
      email        text,
      phone        text,
      source       text NOT NULL DEFAULT 'upload' CHECK (source IN ('upload','apply_link','email','whatsapp')),
      filename     text,
      path         text,
      cv_text      text,
      score        int,
      verdict      text CHECK (verdict IN ('strong','maybe','no')),
      assessment   jsonb NOT NULL DEFAULT '{}',   -- strengths / gaps with the CV line each comes from, interview questions
      status       text NOT NULL DEFAULT 'new' CHECK (status IN ('new','shortlisted','interview','offered','hired','rejected')),
      interview_at timestamptz,
      notes        text,
      created_at   timestamptz NOT NULL DEFAULT now(),
      updated_at   timestamptz NOT NULL DEFAULT now()
    );
    CREATE INDEX ON app.candidates (org_id, job_id, score DESC NULLS LAST);
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
    op.execute("DROP TABLE app.candidates; DROP TABLE app.jobs;")

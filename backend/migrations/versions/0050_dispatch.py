"""Ops dispatcher (ROADMAP-V3 C2, v2 11.4): technicians and the service jobs they're sent to.

Revision ID: 0050
"""
from alembic import op

revision = "0050"
down_revision = "0049"
branch_labels = None
depends_on = None

TABLES = ["technicians", "service_jobs"]


def upgrade() -> None:
    op.execute("""
    CREATE TABLE app.technicians (
      id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      org_id       text NOT NULL,
      name         text NOT NULL,
      phone        text,
      skills       text[] NOT NULL DEFAULT '{}',
      areas        text[] NOT NULL DEFAULT '{}',
      max_per_day  int NOT NULL DEFAULT 5,
      active       boolean NOT NULL DEFAULT true,
      created_at   timestamptz NOT NULL DEFAULT now()
    );
    CREATE TABLE app.service_jobs (
      id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      org_id         text NOT NULL,
      number         int NOT NULL,
      contact_id     uuid REFERENCES app.contacts(id) ON DELETE SET NULL,
      conversation_id uuid REFERENCES app.conversations(id) ON DELETE SET NULL,
      customer       text NOT NULL,
      phone          text,
      address        text,
      area           text,
      service        text NOT NULL,
      description    text,
      day            date NOT NULL,
      slot           text NOT NULL DEFAULT 'any' CHECK (slot IN ('morning','afternoon','evening','any')),
      status         text NOT NULL DEFAULT 'new' CHECK (status IN ('new','assigned','on_the_way','in_progress','done','cancelled')),
      technician_id  uuid REFERENCES app.technicians(id) ON DELETE SET NULL,
      amount         numeric(14,2),
      photos         jsonb NOT NULL DEFAULT '[]',
      notes          text,
      invoice_id     uuid,
      source         text NOT NULL DEFAULT 'person' CHECK (source IN ('agent','person')),
      done_at        timestamptz,
      created_at     timestamptz NOT NULL DEFAULT now(),
      updated_at     timestamptz NOT NULL DEFAULT now(),
      UNIQUE (org_id, number)
    );
    CREATE INDEX ON app.service_jobs (org_id, day, status);
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
    op.execute("DROP TABLE app.service_jobs; DROP TABLE app.technicians;")

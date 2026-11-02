"""Renewals & repeat business (ROADMAP-V3 A4): what each customer renews and when; birthdays for wishes.

Revision ID: 0040
"""
from alembic import op

revision = "0040"
down_revision = "0039"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
    CREATE TABLE app.renewals (
      id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      org_id        text NOT NULL,
      contact_id    uuid REFERENCES app.contacts(id) ON DELETE SET NULL,
      customer      text NOT NULL,
      phone         text,
      email         text,
      item          text NOT NULL,
      due_on        date NOT NULL,
      amount        numeric(14,2),
      every         text NOT NULL DEFAULT 'yearly' CHECK (every IN ('once','monthly','quarterly','half_yearly','yearly')),
      status        text NOT NULL DEFAULT 'upcoming' CHECK (status IN ('upcoming','renewed','lapsed','cancelled')),
      reminded      jsonb NOT NULL DEFAULT '[]',   -- the day offsets already sent for this due date
      winback_sent  boolean NOT NULL DEFAULT false,
      payment_link  text,
      renewals      int NOT NULL DEFAULT 0,
      notes         text,
      created_at    timestamptz NOT NULL DEFAULT now(),
      updated_at    timestamptz NOT NULL DEFAULT now()
    );
    CREATE INDEX ON app.renewals (org_id, status, due_on);
    ALTER TABLE app.renewals ENABLE ROW LEVEL SECURITY;
    ALTER TABLE app.renewals FORCE ROW LEVEL SECURITY;
    CREATE POLICY tenant_isolation ON app.renewals USING (org_id = current_setting('app.org_id', true))
      WITH CHECK (org_id = current_setting('app.org_id', true));
    GRANT SELECT, INSERT, UPDATE, DELETE ON app.renewals TO agentry_app, agentry_system;
    """)


def downgrade() -> None:
    op.execute("DROP TABLE app.renewals;")

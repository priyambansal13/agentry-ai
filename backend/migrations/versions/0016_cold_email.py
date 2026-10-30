"""Personal cold email (Phase 5.1-5.3): prospect lists built per campaign, researched first lines, human review.

A cold-email campaign has no sequence until sending is built (5.4), so campaigns.sequence_id becomes optional.
Funnel counts come from prospect_companies.reached (the furthest step each business got to), not from counters.

Revision ID: 0016
"""
from alembic import op

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None

TENANT_TABLES = ["prospect_companies", "prospects"]


def upgrade() -> None:
    op.execute("""
    ALTER TABLE app.campaigns
      ALTER COLUMN sequence_id DROP NOT NULL,
      ADD COLUMN settings jsonb NOT NULL DEFAULT '{}',        -- cold email: search, city, filters, source
      ADD COLUMN build_status text CHECK (build_status IN ('building','built','failed')),
      ADD COLUMN build_error text,
      ADD COLUMN created_by text;

    CREATE TABLE app.prospect_companies (
      id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      org_id       text NOT NULL,
      campaign_id  uuid NOT NULL REFERENCES app.campaigns(id) ON DELETE CASCADE,
      source       text NOT NULL,                  -- places | csv
      place_id     text,                           -- Places: only the id is kept long term; details are refreshed
      name         text NOT NULL,
      website      text,
      domain       text,
      category     text,
      rating       numeric(2, 1),
      reviews      int,
      city         text,
      address      text,
      phone        text,
      -- furthest funnel step: 0 found, 1 has website, 2 fits the ideal customer, 3 new (not a client, lead or earlier
      -- prospect), 4 decision maker found, 5 email verified, 6 first line ready
      reached      int NOT NULL DEFAULT 0,
      drop_reason  text,
      created_at   timestamptz NOT NULL DEFAULT now(),
      UNIQUE (campaign_id, place_id)
    );
    CREATE INDEX ON app.prospect_companies (org_id, domain);

    CREATE TABLE app.prospects (
      id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      org_id        text NOT NULL,
      campaign_id   uuid NOT NULL REFERENCES app.campaigns(id) ON DELETE CASCADE,
      company_id    uuid NOT NULL REFERENCES app.prospect_companies(id) ON DELETE CASCADE,
      name          text,
      role          text,
      email         text NOT NULL,
      email_source  text NOT NULL CHECK (email_source IN ('site','finder','pattern')),
      verify_status text NOT NULL CHECK (verify_status IN ('valid','catch_all','invalid','unknown')),
      snippets      jsonb NOT NULL DEFAULT '[]',     -- [{n, url, text}] from their own website: the only facts allowed
      summary       text,
      first_line    text,
      line_snippet  int,                             -- which snippet the line is based on
      fact_check    jsonb NOT NULL DEFAULT '{}',     -- {ok, reason, attempts}
      review        text NOT NULL DEFAULT 'pending' CHECK (review IN ('pending','needs_attention','approved','dropped')),
      edited        boolean NOT NULL DEFAULT false,
      reviewed_by   text,
      reviewed_at   timestamptz,
      created_at    timestamptz NOT NULL DEFAULT now(),
      updated_at    timestamptz NOT NULL DEFAULT now(),
      UNIQUE (campaign_id, email)
    );
    CREATE INDEX ON app.prospects (org_id, email);
    """)
    for t in TENANT_TABLES:
        op.execute(f"""
        ALTER TABLE app.{t} ENABLE ROW LEVEL SECURITY;
        ALTER TABLE app.{t} FORCE ROW LEVEL SECURITY;
        CREATE POLICY tenant_isolation ON app.{t}
          USING (org_id = current_setting('app.org_id', true)) WITH CHECK (org_id = current_setting('app.org_id', true));
        GRANT SELECT, INSERT, UPDATE, DELETE ON app.{t} TO agentry_app, agentry_system;
        """)


def downgrade() -> None:
    op.execute("""
    DROP TABLE app.prospects; DROP TABLE app.prospect_companies;
    DELETE FROM app.campaigns WHERE kind = 'cold_email';
    ALTER TABLE app.campaigns DROP COLUMN settings, DROP COLUMN build_status, DROP COLUMN build_error, DROP COLUMN created_by,
      ALTER COLUMN sequence_id SET NOT NULL;
    """)

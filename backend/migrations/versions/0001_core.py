"""Core platform tables: tenancy, contacts, automations, outbox, audit, LLM calls, metrics, onboarding.

Every tenant table has org_id + FORCE ROW LEVEL SECURITY. The API sets app.org_id per transaction
(see agentry.db.tenant_session); a request without it sees nothing.

Revision ID: 0001
"""
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

TENANT_TABLES = [
    "org_settings", "locations", "contacts", "automation_instances", "events",
    "audit_log", "llm_calls", "metrics_daily", "onboarding_progress",
]


def upgrade() -> None:
    op.execute("""
    -- One row per client organisation (the organisation itself lives in auth.organization, owned by Better Auth).
    CREATE TABLE app.org_settings (
      org_id        text PRIMARY KEY,
      status        text NOT NULL DEFAULT 'pending_setup'
                    CHECK (status IN ('pending_setup','onboarding','live','paused','churned','demo')),
      industry_pack text,
      country       text NOT NULL DEFAULT 'IN',
      timezone      text NOT NULL DEFAULT 'Asia/Kolkata',
      currency      text NOT NULL DEFAULT 'INR',
      website       text,
      profile       jsonb NOT NULL DEFAULT '{}',
      created_at    timestamptz NOT NULL DEFAULT now()
    );

    CREATE TABLE app.locations (
      id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      org_id     text NOT NULL,
      name       text NOT NULL,
      address    text,
      timezone   text,
      created_at timestamptz NOT NULL DEFAULT now()
    );
    CREATE INDEX ON app.locations (org_id);

    CREATE TABLE app.contacts (
      id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      org_id      text NOT NULL,
      name        text,
      email       text,
      phone       text,
      company     text,
      source      text,
      attributes  jsonb NOT NULL DEFAULT '{}',
      created_at  timestamptz NOT NULL DEFAULT now()
    );
    CREATE INDEX ON app.contacts (org_id, created_at DESC);
    CREATE INDEX ON app.contacts (org_id, phone);
    CREATE INDEX ON app.contacts (org_id, lower(email));

    CREATE TABLE app.automation_instances (
      id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      org_id       text NOT NULL,
      template_key text NOT NULL,
      status       text NOT NULL DEFAULT 'setup'
                   CHECK (status IN ('setup','approval_mode','live','paused','error')),
      config       jsonb NOT NULL DEFAULT '{}',
      created_at   timestamptz NOT NULL DEFAULT now(),
      UNIQUE (org_id, template_key)
    );

    -- Transactional outbox: written in the same transaction as the change, dispatched by the worker.
    CREATE TABLE app.events (
      id            bigserial PRIMARY KEY,
      org_id        text,
      type          text NOT NULL,
      payload       jsonb NOT NULL DEFAULT '{}',
      occurred_at   timestamptz NOT NULL DEFAULT now(),
      dispatched_at timestamptz,
      attempts      int NOT NULL DEFAULT 0,
      last_error    text
    );
    CREATE INDEX events_undispatched ON app.events (id) WHERE dispatched_at IS NULL;
    CREATE INDEX ON app.events (org_id, type, occurred_at);

    CREATE TABLE app.audit_log (
      id            bigserial PRIMARY KEY,
      org_id        text,
      actor_user_id text,
      actor_type    text NOT NULL CHECK (actor_type IN ('user','agentry_staff','system','agent')),
      action        text NOT NULL,
      target_type   text,
      target_id     text,
      metadata      jsonb NOT NULL DEFAULT '{}',
      ip            text,
      at            timestamptz NOT NULL DEFAULT now()
    );
    CREATE INDEX ON app.audit_log (org_id, at DESC);

    CREATE TABLE app.llm_calls (
      id             bigserial PRIMARY KEY,
      org_id         text,
      tier           text NOT NULL,
      model          text NOT NULL,
      prompt_key     text,
      prompt_version text,
      input_tokens   int,
      output_tokens  int,
      cost_usd       numeric(12,6) NOT NULL DEFAULT 0,
      latency_ms     int,
      status         text NOT NULL,
      error          text,
      at             timestamptz NOT NULL DEFAULT now()
    );
    CREATE INDEX ON app.llm_calls (org_id, at DESC);

    -- Global registry (no tenant data): one definition per metric, shared by dashboard, reports and billing.
    CREATE TABLE app.metric_definitions (
      key              text PRIMARY KEY,
      name             text NOT NULL,
      automation_key   text,
      event_type       text NOT NULL,
      aggregation      text NOT NULL CHECK (aggregation IN ('count','sum')),
      value_path       text,
      unit             text NOT NULL,
      higher_is_better boolean NOT NULL DEFAULT true
    );

    CREATE TABLE app.metrics_daily (
      org_id         text NOT NULL,
      metric_key     text NOT NULL REFERENCES app.metric_definitions(key),
      day            date NOT NULL,
      value          numeric NOT NULL,
      computed_at    timestamptz NOT NULL DEFAULT now(),
      PRIMARY KEY (org_id, metric_key, day)
    );

    CREATE TABLE app.onboarding_progress (
      org_id     text NOT NULL,
      step_key   text NOT NULL,
      status     text NOT NULL DEFAULT 'todo' CHECK (status IN ('todo','in_progress','blocked','done','skipped')),
      done_by    text CHECK (done_by IN ('client','agentry')),
      blocker    text,
      eta        date,
      updated_at timestamptz NOT NULL DEFAULT now(),
      PRIMARY KEY (org_id, step_key)
    );

    -- Platform data (not tenant-scoped): only agentry_system touches it.
    CREATE TABLE app.demo_requests (
      id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      name       text NOT NULL,
      email      text NOT NULL,
      phone      text,
      company    text,
      website    text,
      niche      text,
      message    text,
      status     text NOT NULL DEFAULT 'new' CHECK (status IN ('new','contacted','demo_built','won','lost')),
      created_at timestamptz NOT NULL DEFAULT now()
    );
    """)

    for t in TENANT_TABLES:
        op.execute(f"""
        ALTER TABLE app.{t} ENABLE ROW LEVEL SECURITY;
        ALTER TABLE app.{t} FORCE ROW LEVEL SECURITY;
        CREATE POLICY tenant_isolation ON app.{t}
          USING (org_id = current_setting('app.org_id', true))
          WITH CHECK (org_id = current_setting('app.org_id', true));
        GRANT SELECT, INSERT, UPDATE, DELETE ON app.{t} TO agentry_app;
        """)

    op.execute("""
    GRANT SELECT ON app.metric_definitions TO agentry_app;
    GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA app TO agentry_system;
    GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA app TO agentry_app, agentry_system;
    -- Audit log is append-only for the API.
    REVOKE UPDATE, DELETE ON app.audit_log FROM agentry_app;
    """)


def downgrade() -> None:
    op.execute("""
    DROP TABLE IF EXISTS app.demo_requests, app.onboarding_progress, app.metrics_daily, app.metric_definitions,
      app.llm_calls, app.audit_log, app.events, app.automation_instances, app.contacts, app.locations,
      app.org_settings CASCADE;
    """)

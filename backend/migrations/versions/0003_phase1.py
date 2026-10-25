"""Phase 1: conversations, messages, approvals, knowledge base, booking, leads, per-org agent settings.

Revision ID: 0003
"""
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None

TENANT_TABLES = ["kb_documents", "kb_chunks", "services", "staff", "bookings", "conversations", "messages",
                 "approvals", "leads"]


def upgrade() -> None:
    op.execute("""
    CREATE EXTENSION IF NOT EXISTS btree_gist;

    ALTER TABLE app.org_settings
      ADD COLUMN persona        jsonb NOT NULL DEFAULT '{}',   -- agent name, tone, greeting, languages
      ADD COLUMN qualification  jsonb NOT NULL DEFAULT '[]',   -- questions every agent asks (pack default: need/budget/timeline)
      ADD COLUMN brand          jsonb NOT NULL DEFAULT '{}',   -- logo url, colours (Demo Studio, widget)
      ADD COLUMN llm_models     jsonb NOT NULL DEFAULT '{}',   -- per-client tier override: {"writer": ["openai/...", "gemini/..."]}
      ADD COLUMN widget_key     text UNIQUE,                   -- public key for the website chat widget
      ADD COLUMN demo_expires_at timestamptz;                  -- Demo Studio tenants expire

    ALTER TABLE app.automation_instances ADD COLUMN updated_at timestamptz NOT NULL DEFAULT now();

    -- Knowledge base: documents (a crawled page, an FAQ entry, a pasted text) split into embedded chunks.
    CREATE TABLE app.kb_documents (
      id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      org_id      text NOT NULL,
      source_type text NOT NULL CHECK (source_type IN ('url','faq','text')),
      source_ref  text,
      title       text,
      content     text NOT NULL,
      created_at  timestamptz NOT NULL DEFAULT now(),
      updated_at  timestamptz NOT NULL DEFAULT now()
    );
    CREATE INDEX ON app.kb_documents (org_id);
    CREATE TABLE app.kb_chunks (
      id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      org_id      text NOT NULL,
      document_id uuid NOT NULL REFERENCES app.kb_documents(id) ON DELETE CASCADE,
      ord         int NOT NULL,
      content     text NOT NULL,
      embedding   vector(768) NOT NULL
    );
    CREATE INDEX ON app.kb_chunks (org_id);
    CREATE INDEX kb_chunks_embedding ON app.kb_chunks USING hnsw (embedding vector_cosine_ops);

    -- Booking service (shared by chat, receptionist, speed-to-lead, reactivation).
    CREATE TABLE app.services (
      id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      org_id     text NOT NULL,
      key        text NOT NULL,
      name       text NOT NULL,
      minutes    int NOT NULL CHECK (minutes BETWEEN 5 AND 480),
      price      numeric,
      active     boolean NOT NULL DEFAULT true,
      UNIQUE (org_id, key)
    );
    CREATE TABLE app.staff (
      id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      org_id        text NOT NULL,
      name          text NOT NULL,
      email         text,
      service_keys  text[] NOT NULL DEFAULT '{}',
      working_hours jsonb NOT NULL DEFAULT '{}',  -- {"mon": [["10:00","20:00"]], ...} in the org's timezone
      active        boolean NOT NULL DEFAULT true
    );
    CREATE TABLE app.leads (
      id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      org_id          text NOT NULL,
      contact_id      uuid REFERENCES app.contacts(id),
      source          text NOT NULL,
      stage           text NOT NULL DEFAULT 'new'
                      CHECK (stage IN ('new','contacted','engaged','qualified','booked','showed','won','lost',
                                       'no_show','nurture','disqualified','opted_out','human')),
      qualification   jsonb NOT NULL DEFAULT '{}',
      conversation_id uuid,
      created_at      timestamptz NOT NULL DEFAULT now(),
      updated_at      timestamptz NOT NULL DEFAULT now()
    );
    CREATE INDEX ON app.leads (org_id, stage);
    CREATE TABLE app.bookings (
      id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      org_id          text NOT NULL,
      staff_id        uuid NOT NULL REFERENCES app.staff(id),
      service_id      uuid NOT NULL REFERENCES app.services(id),
      contact_id      uuid REFERENCES app.contacts(id),
      lead_id         uuid REFERENCES app.leads(id),
      starts_at       timestamptz NOT NULL,
      ends_at         timestamptz NOT NULL,
      status          text NOT NULL DEFAULT 'booked' CHECK (status IN ('booked','confirmed','cancelled','showed','no_show')),
      source          text NOT NULL,
      conversation_id uuid,
      created_at      timestamptz NOT NULL DEFAULT now(),
      CHECK (ends_at > starts_at),
      -- The database itself refuses double-booking a staff member, however many agents book at once.
      EXCLUDE USING gist (staff_id WITH =, tstzrange(starts_at, ends_at) WITH &&)
        WHERE (status IN ('booked','confirmed'))
    );
    CREATE INDEX ON app.bookings (org_id, starts_at);

    -- Conversations on any channel, and their messages.
    CREATE TABLE app.conversations (
      id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      org_id          text NOT NULL,
      channel         text NOT NULL CHECK (channel IN ('email','web_chat','whatsapp','sms','voice')),
      automation_key  text,
      contact_id      uuid REFERENCES app.contacts(id),
      subject         text,
      status          text NOT NULL DEFAULT 'open' CHECK (status IN ('open','handed_off','closed')),
      external_ref    text,
      metadata        jsonb NOT NULL DEFAULT '{}',
      created_at      timestamptz NOT NULL DEFAULT now(),
      last_message_at timestamptz NOT NULL DEFAULT now(),
      UNIQUE (org_id, channel, external_ref)
    );
    CREATE INDEX ON app.conversations (org_id, last_message_at DESC);
    CREATE TABLE app.messages (
      id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      org_id          text NOT NULL,
      conversation_id uuid NOT NULL REFERENCES app.conversations(id) ON DELETE CASCADE,
      direction       text NOT NULL CHECK (direction IN ('in','out')),
      author          text NOT NULL CHECK (author IN ('contact','agent','human','system')),
      body            text NOT NULL,
      metadata        jsonb NOT NULL DEFAULT '{}',
      created_at      timestamptz NOT NULL DEFAULT now()
    );
    CREATE INDEX ON app.messages (conversation_id, created_at);
    CREATE INDEX messages_triage_category ON app.messages (org_id, (metadata #>> '{triage,category}'));

    -- "Needs you": anything waiting for a human decision.
    CREATE TABLE app.approvals (
      id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      org_id          text NOT NULL,
      kind            text NOT NULL CHECK (kind IN ('reply_draft','escalation','dispute','low_confidence','handoff')),
      status          text NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','approved','edited','rejected','resolved')),
      automation_key  text,
      conversation_id uuid REFERENCES app.conversations(id) ON DELETE CASCADE,
      title           text NOT NULL,
      body            text,
      payload         jsonb NOT NULL DEFAULT '{}',
      created_at      timestamptz NOT NULL DEFAULT now(),
      decided_by      text,
      decided_at      timestamptz
    );
    CREATE INDEX ON app.approvals (org_id, status, created_at DESC);

    -- LangGraph checkpoints (agent conversation state) live in their own schema, owned by the worker role.
    CREATE SCHEMA IF NOT EXISTS agent AUTHORIZATION agentry_system;
    """)
    for t in TENANT_TABLES:
        op.execute(f"""
        ALTER TABLE app.{t} ENABLE ROW LEVEL SECURITY;
        ALTER TABLE app.{t} FORCE ROW LEVEL SECURITY;
        CREATE POLICY tenant_isolation ON app.{t}
          USING (org_id = current_setting('app.org_id', true))
          WITH CHECK (org_id = current_setting('app.org_id', true));
        GRANT SELECT, INSERT, UPDATE, DELETE ON app.{t} TO agentry_app;
        GRANT SELECT, INSERT, UPDATE, DELETE ON app.{t} TO agentry_system;
        """)


def downgrade() -> None:
    op.execute("""
    DROP TABLE IF EXISTS app.approvals, app.messages, app.conversations, app.bookings, app.leads, app.staff,
      app.services, app.kb_chunks, app.kb_documents CASCADE;
    ALTER TABLE app.org_settings DROP COLUMN persona, DROP COLUMN qualification, DROP COLUMN brand,
      DROP COLUMN llm_models, DROP COLUMN widget_key, DROP COLUMN demo_expires_at;
    ALTER TABLE app.automation_instances DROP COLUMN updated_at;
    """)

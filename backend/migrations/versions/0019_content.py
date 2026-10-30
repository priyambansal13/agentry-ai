"""Content repurposing (Phase 6.1-6.4): uploaded videos/podcasts, their transcripts, the best moments, a post per
moment and platform with its image, the review state and the calendar slot; one brand kit per client.

Revision ID: 0019
"""
from alembic import op

revision = "0019"
down_revision = "0018"
branch_labels = None
depends_on = None

TENANT_TABLES = ["brand_kits", "content_sources", "content_moments", "content_posts"]


def upgrade() -> None:
    op.execute("""
    CREATE TABLE app.brand_kits (
      org_id      text PRIMARY KEY,
      primary_color text NOT NULL DEFAULT '#1F2A1A',   -- card background / text
      accent_color  text NOT NULL DEFAULT '#C8F04A',   -- highlight
      template    text NOT NULL DEFAULT 'bold' CHECK (template IN ('bold','light','split')),
      logo_path   text,                                -- var/content/<org>/brand/logo.png
      voice       text,                                -- how they write, learned from past posts
      voice_samples int NOT NULL DEFAULT 0,
      handle      text,                                -- shown on cards, e.g. @smilecraftdental
      platforms   text[] NOT NULL DEFAULT '{linkedin,instagram,x}',
      moments_per_source int NOT NULL DEFAULT 10 CHECK (moments_per_source BETWEEN 3 AND 20),
      updated_at  timestamptz NOT NULL DEFAULT now()
    );

    CREATE TABLE app.content_sources (
      id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      org_id      text NOT NULL,
      title       text NOT NULL,
      kind        text NOT NULL CHECK (kind IN ('video','audio','transcript','sample')),
      file_path   text,
      file_bytes  bigint,
      status      text NOT NULL DEFAULT 'uploaded'
                  CHECK (status IN ('uploaded','transcribing','finding_moments','writing','ready','failed')),
      error       text,
      transcript  jsonb,                               -- {language, duration_seconds, segments: [{start, end, speaker, text}]}
      progress    jsonb NOT NULL DEFAULT '{}',
      cost_usd    numeric(10, 4) NOT NULL DEFAULT 0,
      created_by  text,
      created_at  timestamptz NOT NULL DEFAULT now(),
      ready_at    timestamptz
    );

    CREATE TABLE app.content_moments (
      id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      org_id      text NOT NULL,
      source_id   uuid NOT NULL REFERENCES app.content_sources(id) ON DELETE CASCADE,
      rank        int NOT NULL,
      start_s     numeric(8, 1) NOT NULL,
      end_s       numeric(8, 1) NOT NULL,
      quote       text NOT NULL,                       -- exact words from the transcript
      speaker     text,
      hook        text NOT NULL,
      insight     text NOT NULL,
      topic       text,
      score       numeric(5, 2) NOT NULL,
      dropped     boolean NOT NULL DEFAULT false
    );

    CREATE TABLE app.content_posts (
      id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      org_id      text NOT NULL,
      source_id   uuid NOT NULL REFERENCES app.content_sources(id) ON DELETE CASCADE,
      moment_id   uuid NOT NULL REFERENCES app.content_moments(id) ON DELETE CASCADE,
      platform    text NOT NULL CHECK (platform IN ('linkedin','instagram','x')),
      body        text NOT NULL,
      hashtags    text[] NOT NULL DEFAULT '{}',
      critic      jsonb NOT NULL DEFAULT '{}',         -- {ok, problems, attempts}
      image_path  text,
      review      text NOT NULL DEFAULT 'pending' CHECK (review IN ('pending','needs_attention','approved','dropped')),
      edited      boolean NOT NULL DEFAULT false,
      reviewed_by text,
      reviewed_at timestamptz,
      scheduled_at timestamptz,
      published_at timestamptz,
      publish_ref text,                                -- the platform's post id / link (mock in test mode)
      publish_error text,
      created_at  timestamptz NOT NULL DEFAULT now(),
      updated_at  timestamptz NOT NULL DEFAULT now(),
      UNIQUE (moment_id, platform)
    );
    CREATE INDEX ON app.content_posts (org_id, scheduled_at) WHERE published_at IS NULL;
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
    op.execute("DROP TABLE app.content_posts; DROP TABLE app.content_moments; DROP TABLE app.content_sources; DROP TABLE app.brand_kits;")

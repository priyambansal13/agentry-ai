"""AI video studio (docs/flows/agents/ai-video-studio.md): short videos planned, generated with Veo, composed with the
brand, reviewed and published to YouTube. Adds the YouTube connection.

Revision ID: 0037
"""
from alembic import op

revision = "0037"
down_revision = "0036"
branch_labels = None
depends_on = None

KINDS = ("'reply_draft','outbound_draft','escalation','dispute','low_confidence','handoff','payment_review','callback','document_review',"
         "'ca_task'")
PROVIDERS = "'gmail','outlook','whatsapp','razorpay','stripe','phone','telegram','instagram','linkedin','google_sheets'"


def upgrade() -> None:
    op.execute(f"""
    CREATE TABLE app.ai_videos (
      id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      org_id        text NOT NULL,
      status        text NOT NULL DEFAULT 'planning' CHECK (status IN ('planning','needs_attention','generating','composing','review',
                      'publishing','published','rejected','failed','skipped')),
      trigger       text NOT NULL DEFAULT 'manual' CHECK (trigger IN ('manual','schedule')),
      slot          text,                 -- the schedule slot it was made for (YYYY-MM-DD HH:MM), never twice
      topic         text,
      plan          jsonb NOT NULL DEFAULT '{{}}',   -- title, description, hashtags, hook, scenes [{{prompt, caption}}]
      checks        jsonb NOT NULL DEFAULT '[]',
      ops           jsonb NOT NULL DEFAULT '[]',     -- one Veo operation per scene: {{name, status, path}}
      model         text,
      seconds       numeric,
      cost_usd      numeric(10,2) NOT NULL DEFAULT 0,
      path          text,
      publish       jsonb NOT NULL DEFAULT '{{}}',   -- {{platform, id, url, privacy, at}}
      error         text,
      created_by    text,
      created_at    timestamptz NOT NULL DEFAULT now(),
      updated_at    timestamptz NOT NULL DEFAULT now(),
      UNIQUE (org_id, slot)
    );
    CREATE INDEX ON app.ai_videos (org_id, created_at DESC);
    ALTER TABLE app.ai_videos ENABLE ROW LEVEL SECURITY;
    ALTER TABLE app.ai_videos FORCE ROW LEVEL SECURITY;
    CREATE POLICY tenant_isolation ON app.ai_videos USING (org_id = current_setting('app.org_id', true))
      WITH CHECK (org_id = current_setting('app.org_id', true));
    GRANT SELECT, INSERT, UPDATE, DELETE ON app.ai_videos TO agentry_app, agentry_system;
    ALTER TABLE app.connections DROP CONSTRAINT connections_provider_check;
    ALTER TABLE app.connections ADD CONSTRAINT connections_provider_check CHECK (provider IN ({PROVIDERS},'youtube'));
    ALTER TABLE app.approvals DROP CONSTRAINT approvals_kind_check;
    ALTER TABLE app.approvals ADD CONSTRAINT approvals_kind_check CHECK (kind IN ({KINDS},'video_review'));
    """)


def downgrade() -> None:
    op.execute(f"""
    DELETE FROM app.approvals WHERE kind = 'video_review';
    ALTER TABLE app.approvals DROP CONSTRAINT approvals_kind_check;
    ALTER TABLE app.approvals ADD CONSTRAINT approvals_kind_check CHECK (kind IN ({KINDS}));
    DELETE FROM app.connections WHERE provider = 'youtube';
    ALTER TABLE app.connections DROP CONSTRAINT connections_provider_check;
    ALTER TABLE app.connections ADD CONSTRAINT connections_provider_check CHECK (provider IN ({PROVIDERS}));
    DROP TABLE app.ai_videos;
    """)

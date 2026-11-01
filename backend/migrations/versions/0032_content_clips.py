"""Content v2 (ROADMAP-V2 8.2): vertical clips, one per moment of a video upload.

    content_clips   the moment's 9:16 MP4 (captions, hook banner, end card): where it is, the cut (start/end in the
                    source), its length, and ready | failed | skipped (a moment past the end of the video)

Revision ID: 0032
"""
from alembic import op

revision = "0032"
down_revision = "0031"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
    CREATE TABLE app.content_clips (
      id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      org_id       text NOT NULL,
      source_id    uuid NOT NULL REFERENCES app.content_sources(id) ON DELETE CASCADE,
      moment_id    uuid NOT NULL UNIQUE REFERENCES app.content_moments(id) ON DELETE CASCADE,
      status       text NOT NULL DEFAULT 'cutting' CHECK (status IN ('cutting','ready','failed','skipped')),
      path         text,
      start_s      numeric,
      end_s        numeric,
      duration_s   numeric,
      error        text,
      created_at   timestamptz NOT NULL DEFAULT now(),
      updated_at   timestamptz NOT NULL DEFAULT now()
    );
    CREATE INDEX content_clips_source ON app.content_clips (source_id);
    ALTER TABLE app.content_clips ENABLE ROW LEVEL SECURITY;
    ALTER TABLE app.content_clips FORCE ROW LEVEL SECURITY;
    CREATE POLICY tenant_isolation ON app.content_clips
      USING (org_id = current_setting('app.org_id', true)) WITH CHECK (org_id = current_setting('app.org_id', true));
    GRANT SELECT, INSERT, UPDATE, DELETE ON app.content_clips TO agentry_app, agentry_system;
    ALTER TABLE app.content_sources DROP CONSTRAINT content_sources_status_check;
    ALTER TABLE app.content_sources ADD CONSTRAINT content_sources_status_check
      CHECK (status IN ('uploaded','transcribing','finding_moments','writing','cutting_clips','ready','failed'));
    """)


def downgrade() -> None:
    op.execute("""DROP TABLE app.content_clips;
    ALTER TABLE app.content_sources DROP CONSTRAINT content_sources_status_check;
    ALTER TABLE app.content_sources ADD CONSTRAINT content_sources_status_check
      CHECK (status IN ('uploaded','transcribing','finding_moments','writing','ready','failed'));""")

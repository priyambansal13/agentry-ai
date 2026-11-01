"""Content from a link (YouTube, Vimeo, Instagram, a direct MP4…): the recording keeps the link it came from, and a
'downloading' step comes before transcription.

Revision ID: 0033
"""
from alembic import op

revision = "0033"
down_revision = "0032"
branch_labels = None
depends_on = None

STATUSES = "'uploaded','transcribing','finding_moments','writing','cutting_clips','ready','failed'"


def upgrade() -> None:
    op.execute(f"""
    ALTER TABLE app.content_sources ADD COLUMN source_url text;
    ALTER TABLE app.content_sources DROP CONSTRAINT content_sources_status_check;
    ALTER TABLE app.content_sources ADD CONSTRAINT content_sources_status_check CHECK (status IN ('downloading',{STATUSES}));
    """)


def downgrade() -> None:
    op.execute(f"""
    ALTER TABLE app.content_sources DROP CONSTRAINT content_sources_status_check;
    ALTER TABLE app.content_sources ADD CONSTRAINT content_sources_status_check CHECK (status IN ({STATUSES}));
    ALTER TABLE app.content_sources DROP COLUMN source_url;
    """)

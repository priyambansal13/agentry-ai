"""Agentry's own sales pipeline: demo requests get statuses, notes, their demo, follow-ups and the client they became.

Revision ID: 0012
"""
from alembic import op

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
    ALTER TABLE app.demo_requests DROP CONSTRAINT demo_requests_status_check;
    UPDATE app.demo_requests SET status = 'in_talks' WHERE status = 'contacted';
    ALTER TABLE app.demo_requests ADD CONSTRAINT demo_requests_status_check
      CHECK (status IN ('new','demo_built','demo_sent','in_talks','won','lost'));
    ALTER TABLE app.demo_requests
      ADD COLUMN notes text,
      ADD COLUMN demo_org_id text,
      ADD COLUMN demo_slug text,
      ADD COLUMN video_url text,
      ADD COLUMN demo_sent_at timestamptz,
      ADD COLUMN followups_sent int NOT NULL DEFAULT 0,
      ADD COLUMN lead_id uuid,
      ADD COLUMN client_org_id text,
      ADD COLUMN updated_at timestamptz NOT NULL DEFAULT now();
    """)


def downgrade() -> None:
    op.execute("""
    ALTER TABLE app.demo_requests DROP COLUMN notes, DROP COLUMN demo_org_id, DROP COLUMN demo_slug, DROP COLUMN video_url,
      DROP COLUMN demo_sent_at, DROP COLUMN followups_sent, DROP COLUMN lead_id, DROP COLUMN client_org_id, DROP COLUMN updated_at;
    ALTER TABLE app.demo_requests DROP CONSTRAINT demo_requests_status_check;
    UPDATE app.demo_requests SET status = 'contacted' WHERE status IN ('demo_sent','in_talks');
    UPDATE app.demo_requests SET status = 'demo_built' WHERE status = 'demo_built';
    ALTER TABLE app.demo_requests ADD CONSTRAINT demo_requests_status_check
      CHECK (status IN ('new','contacted','demo_built','won','lost'));
    """)

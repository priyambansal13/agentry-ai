"""Voice: "Call back" cards in Needs you, and how long each client keeps call recordings.

Revision ID: 0010
"""
from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
    ALTER TABLE app.approvals DROP CONSTRAINT approvals_kind_check;
    ALTER TABLE app.approvals ADD CONSTRAINT approvals_kind_check
      CHECK (kind IN ('reply_draft','outbound_draft','escalation','dispute','low_confidence','handoff','payment_review','callback'));
    ALTER TABLE app.org_settings ADD COLUMN IF NOT EXISTS recording_retention_days int NOT NULL DEFAULT 90
      CHECK (recording_retention_days BETWEEN 7 AND 730);
    """)


def downgrade() -> None:
    op.execute("""
    ALTER TABLE app.org_settings DROP COLUMN recording_retention_days;
    UPDATE app.approvals SET kind = 'handoff' WHERE kind = 'callback';
    ALTER TABLE app.approvals DROP CONSTRAINT approvals_kind_check;
    ALTER TABLE app.approvals ADD CONSTRAINT approvals_kind_check
      CHECK (kind IN ('reply_draft','outbound_draft','escalation','dispute','low_confidence','handoff','payment_review'));
    """)

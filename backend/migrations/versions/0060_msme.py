"""MSME 45-day recovery (docs/PLAN-COMMERCIAL-2026-11.md #4): the business's MSME registration, used by invoice follow-up.

Revision ID: 0060
"""
from alembic import op

revision = "0060"
down_revision = "0059"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # {enabled, udyam, category: micro|small}; a customer's written credit days live on contacts.attributes.credit_days
    op.execute("ALTER TABLE app.org_settings ADD COLUMN msme jsonb NOT NULL DEFAULT '{}';")


def downgrade() -> None:
    op.execute("ALTER TABLE app.org_settings DROP COLUMN msme;")

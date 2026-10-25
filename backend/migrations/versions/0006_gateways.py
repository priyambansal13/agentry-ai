"""Payment gateway connections (Razorpay, Stripe) per client.

Revision ID: 0006
"""
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
    ALTER TABLE app.connections DROP CONSTRAINT connections_provider_check;
    ALTER TABLE app.connections ADD CONSTRAINT connections_provider_check
      CHECK (provider IN ('gmail','outlook','whatsapp','razorpay','stripe'));
    """)


def downgrade() -> None:
    pass

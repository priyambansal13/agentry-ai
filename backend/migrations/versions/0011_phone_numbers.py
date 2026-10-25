"""Phone numbers as connections: a client's receptionist number (provider 'phone', account_ref = E.164).

Revision ID: 0011
"""
from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
    ALTER TABLE app.connections DROP CONSTRAINT connections_provider_check;
    ALTER TABLE app.connections ADD CONSTRAINT connections_provider_check
      CHECK (provider IN ('gmail','outlook','whatsapp','razorpay','stripe','phone'));
    """)


def downgrade() -> None:
    op.execute("""
    DELETE FROM app.connections WHERE provider = 'phone';
    ALTER TABLE app.connections DROP CONSTRAINT connections_provider_check;
    ALTER TABLE app.connections ADD CONSTRAINT connections_provider_check
      CHECK (provider IN ('gmail','outlook','whatsapp','razorpay','stripe'));
    """)

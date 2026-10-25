"""Invoice follow-up fixes: payment links follow the balance (amount + provider), and the "reminders ended" card is
created once per invoice.

Revision ID: 0015
"""
from alembic import op

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
    ALTER TABLE app.invoices
      ADD COLUMN payment_link_amount numeric(14, 2),
      ADD COLUMN payment_link_provider text,
      ADD COLUMN reminders_ended_at timestamptz;
    """)


def downgrade() -> None:
    op.execute("ALTER TABLE app.invoices DROP COLUMN payment_link_amount, DROP COLUMN payment_link_provider, DROP COLUMN reminders_ended_at;")

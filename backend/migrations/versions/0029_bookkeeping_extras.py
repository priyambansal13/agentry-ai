"""Bookkeeping extras (9.5): Google Sheets as a connection, and which documents are already in the sheet.

Revision ID: 0029
"""
from alembic import op

revision = "0029"
down_revision = "0028"
branch_labels = None
depends_on = None

BEFORE = "'gmail','outlook','whatsapp','razorpay','stripe','phone','telegram','instagram','linkedin'"


def upgrade() -> None:
    op.execute(f"""
    ALTER TABLE app.connections DROP CONSTRAINT connections_provider_check;
    ALTER TABLE app.connections ADD CONSTRAINT connections_provider_check CHECK (provider IN ({BEFORE},'google_sheets'));
    ALTER TABLE app.documents ADD COLUMN sheet_synced_at timestamptz;
    """)


def downgrade() -> None:
    op.execute(f"""
    ALTER TABLE app.documents DROP COLUMN sheet_synced_at;
    DELETE FROM app.connections WHERE provider = 'google_sheets';
    ALTER TABLE app.connections DROP CONSTRAINT connections_provider_check;
    ALTER TABLE app.connections ADD CONSTRAINT connections_provider_check CHECK (provider IN ({BEFORE}));
    """)

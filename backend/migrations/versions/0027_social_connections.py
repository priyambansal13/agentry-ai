"""Content publishing (6.5): Instagram (and LinkedIn, next) as connection providers.

Revision ID: 0027
"""
from alembic import op

revision = "0027"
down_revision = "0026"
branch_labels = None
depends_on = None

BEFORE = "'gmail','outlook','whatsapp','razorpay','stripe','phone','telegram'"


def upgrade() -> None:
    op.execute(f"""
    ALTER TABLE app.connections DROP CONSTRAINT connections_provider_check;
    ALTER TABLE app.connections ADD CONSTRAINT connections_provider_check CHECK (provider IN ({BEFORE},'instagram','linkedin'));
    """)


def downgrade() -> None:
    op.execute(f"""
    DELETE FROM app.connections WHERE provider IN ('instagram','linkedin');
    ALTER TABLE app.connections DROP CONSTRAINT connections_provider_check;
    ALTER TABLE app.connections ADD CONSTRAINT connections_provider_check CHECK (provider IN ({BEFORE}));
    """)

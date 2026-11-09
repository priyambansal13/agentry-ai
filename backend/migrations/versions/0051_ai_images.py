"""AI images (ROADMAP-V2 8.7): an opt-in generated background behind content quote cards.

Revision ID: 0051
"""
from alembic import op

revision = "0051"
down_revision = "0050"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
    ALTER TABLE app.brand_kits
      ADD COLUMN ai_images boolean NOT NULL DEFAULT false,
      ADD COLUMN image_style text,
      ADD COLUMN images_per_month int NOT NULL DEFAULT 40;
    ALTER TABLE app.content_moments ADD COLUMN ai_bg_path text;
    """)


def downgrade() -> None:
    op.execute("""
    ALTER TABLE app.content_moments DROP COLUMN ai_bg_path;
    ALTER TABLE app.brand_kits DROP COLUMN ai_images, DROP COLUMN image_style, DROP COLUMN images_per_month;
    """)

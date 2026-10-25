"""Disputes can end in a partial credit: the line stays, a credit line is added, chosen results are excluded.

Revision ID: 0009
"""
from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
    ALTER TABLE app.statement_lines DROP CONSTRAINT statement_lines_dispute_resolution_check;
    ALTER TABLE app.statement_lines ADD CONSTRAINT statement_lines_dispute_resolution_check
      CHECK (dispute_resolution IN ('accepted','rejected','partial'));
    ALTER TABLE app.statement_lines ADD COLUMN IF NOT EXISTS credit_for uuid REFERENCES app.statement_lines(id) ON DELETE CASCADE;
    """)


def downgrade() -> None:
    op.execute("""
    DELETE FROM app.statement_lines WHERE credit_for IS NOT NULL;
    ALTER TABLE app.statement_lines DROP COLUMN credit_for;
    UPDATE app.statement_lines SET dispute_resolution = 'rejected' WHERE dispute_resolution = 'partial';
    ALTER TABLE app.statement_lines DROP CONSTRAINT statement_lines_dispute_resolution_check;
    ALTER TABLE app.statement_lines ADD CONSTRAINT statement_lines_dispute_resolution_check CHECK (dispute_resolution IN ('accepted','rejected'));
    """)

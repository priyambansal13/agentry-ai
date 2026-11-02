"""Client health (ROADMAP-V3 A7) reads when a client's people last used the portal: only the user and the time
columns of Better Auth's sessions, never the tokens.

Revision ID: 0043
"""
from alembic import op

revision = "0043"
down_revision = "0042"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute('GRANT SELECT ("userId", "updatedAt") ON auth.session TO agentry_system')


def downgrade() -> None:
    op.execute('REVOKE SELECT ("userId", "updatedAt") ON auth.session FROM agentry_system')

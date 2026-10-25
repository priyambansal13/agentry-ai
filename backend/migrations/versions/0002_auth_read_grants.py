"""Read access to Better Auth's non-secret tables for the API and workers.

Requires the auth tables to exist: run `pnpm --filter @agentry/dashboard auth:migrate` first.
Secret-bearing tables (jwks: private keys, account: password hashes, session, verification) stay unreadable.

Revision ID: 0002
"""
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

READABLE = ['auth."user"', "auth.organization", "auth.member", "auth.invitation"]
SECRET = ["auth.jwks", "auth.account", "auth.session", "auth.verification"]


def upgrade() -> None:
    op.execute("ALTER DEFAULT PRIVILEGES FOR ROLE agentry_auth IN SCHEMA auth REVOKE SELECT ON TABLES FROM agentry_app, agentry_system")
    for t in SECRET:
        op.execute(f"REVOKE ALL ON {t} FROM agentry_app, agentry_system")
    for t in READABLE:
        op.execute(f"GRANT SELECT ON {t} TO agentry_app, agentry_system")


def downgrade() -> None:
    for t in READABLE:
        op.execute(f"REVOKE SELECT ON {t} FROM agentry_app, agentry_system")

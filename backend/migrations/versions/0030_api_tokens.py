"""Personal access tokens for the Agentry MCP server (ROADMAP-V2 2.6): one person, one business, read-only.

Only the SHA-256 of a token is stored; the token itself is shown once. The person's role is looked up on every call,
so changing or removing their role changes what the token can read at once.

Revision ID: 0030
"""
from alembic import op

revision = "0030"
down_revision = "0029"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
    CREATE TABLE app.api_tokens (
      id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      org_id        text NOT NULL,
      user_id       text NOT NULL,
      name          text NOT NULL,
      token_hash    text NOT NULL UNIQUE,
      prefix        text NOT NULL,
      created_at    timestamptz NOT NULL DEFAULT now(),
      last_used_at  timestamptz,
      revoked_at    timestamptz
    );
    CREATE INDEX ON app.api_tokens (org_id, user_id);
    ALTER TABLE app.api_tokens ENABLE ROW LEVEL SECURITY;
    ALTER TABLE app.api_tokens FORCE ROW LEVEL SECURITY;
    CREATE POLICY tenant_isolation ON app.api_tokens
      USING (org_id = current_setting('app.org_id', true)) WITH CHECK (org_id = current_setting('app.org_id', true));
    GRANT SELECT, INSERT, UPDATE, DELETE ON app.api_tokens TO agentry_app, agentry_system;
    """)


def downgrade() -> None:
    op.execute("DROP TABLE app.api_tokens;")

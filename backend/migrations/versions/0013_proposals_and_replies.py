"""Sent proposals (a fixed snapshot behind a private link) and replies found in Agentry's sales inbox.

Revision ID: 0013
"""
from alembic import op

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
    CREATE TABLE app.proposals (
      id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      token            text NOT NULL UNIQUE,                 -- the private link: /proposal/<token>
      demo_request_id  uuid REFERENCES app.demo_requests(id) ON DELETE SET NULL,
      email            text NOT NULL,
      business         text NOT NULL,
      snapshot         jsonb NOT NULL,                       -- exactly what was shown (ProposalDocument props)
      plan             jsonb,                                -- the pricing plan behind it, to apply when they sign
      note             text,
      sent_by          text,
      sent_at          timestamptz NOT NULL DEFAULT now(),
      first_viewed_at  timestamptz,
      views            int NOT NULL DEFAULT 0
    );
    CREATE INDEX ON app.proposals (demo_request_id);
    CREATE TABLE app.demo_request_messages (
      id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      demo_request_id  uuid NOT NULL REFERENCES app.demo_requests(id) ON DELETE CASCADE,
      message_id       text NOT NULL UNIQUE,                 -- the email's Message-ID: each reply is recorded once
      kind             text NOT NULL CHECK (kind IN ('reply', 'auto_reply', 'bounce')),
      from_address     text,
      subject          text,
      snippet          text,
      received_at      timestamptz NOT NULL,
      created_at       timestamptz NOT NULL DEFAULT now()
    );
    CREATE INDEX ON app.demo_request_messages (demo_request_id, received_at);
    GRANT SELECT, INSERT, UPDATE, DELETE ON app.proposals, app.demo_request_messages TO agentry_system;
    """)


def downgrade() -> None:
    op.execute("DROP TABLE app.demo_request_messages; DROP TABLE app.proposals;")

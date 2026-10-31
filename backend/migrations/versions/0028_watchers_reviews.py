"""Watchers (ROADMAP-V2 7.3) and Review management (9.2).

    watchers          something checked on a schedule: a web page (competitor, price) or a business's reviews. The page
                      is fetched each time, but the model only runs when its content hash changed.
    watch_snapshots   each change: the extracted value, what changed, a short summary
    reviews           customer reviews (Google Business Profile once connected; a sample source until then), classified
                      (sentiment, topics, urgency) with a drafted reply that a person approves before it's posted
    review_requests   "would you leave us a review?" messages after a visit or a paid invoice: once per customer per 90 days

Revision ID: 0028
"""
from alembic import op

revision = "0028"
down_revision = "0027"
branch_labels = None
depends_on = None

TABLES = ("watchers", "watch_snapshots", "reviews", "review_requests")


def upgrade() -> None:
    op.execute("""
    CREATE TABLE app.watchers (
      id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      org_id           text NOT NULL,
      kind             text NOT NULL CHECK (kind IN ('page','price','reviews')),
      name             text NOT NULL,
      url              text,
      every_minutes    int NOT NULL DEFAULT 360 CHECK (every_minutes >= 15),
      rule             jsonb NOT NULL DEFAULT '{}',      -- {"min_change_pct": 5} for prices; {} = any meaningful change
      status           text NOT NULL DEFAULT 'active' CHECK (status IN ('active','paused','error')),
      last_hash        text,
      last_value       jsonb,
      last_checked_at  timestamptz,
      last_changed_at  timestamptz,
      next_check_at    timestamptz NOT NULL DEFAULT now(),
      error            text,
      created_by       text,
      created_at       timestamptz NOT NULL DEFAULT now()
    );
    CREATE INDEX ON app.watchers (next_check_at) WHERE status = 'active';
    CREATE TABLE app.watch_snapshots (
      id          bigserial PRIMARY KEY,
      org_id      text NOT NULL,
      watcher_id  uuid NOT NULL REFERENCES app.watchers(id) ON DELETE CASCADE,
      at          timestamptz NOT NULL DEFAULT now(),
      hash        text NOT NULL,
      value       jsonb,
      changes     jsonb NOT NULL DEFAULT '[]',
      summary     text,
      notified    boolean NOT NULL DEFAULT false
    );
    CREATE INDEX ON app.watch_snapshots (watcher_id, at DESC);
    CREATE TABLE app.reviews (
      id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      org_id        text NOT NULL,
      source        text NOT NULL CHECK (source IN ('google','sample','manual')),
      external_id   text NOT NULL,
      author        text,
      rating        int CHECK (rating BETWEEN 1 AND 5),
      body          text,
      reviewed_at   timestamptz NOT NULL,
      sentiment     text CHECK (sentiment IN ('positive','mixed','negative')),
      topics        text[] NOT NULL DEFAULT '{}',
      urgent        boolean NOT NULL DEFAULT false,
      reply         text,
      reply_status  text NOT NULL DEFAULT 'none' CHECK (reply_status IN ('none','drafted','posted','skipped')),
      replied_at    timestamptz,
      approval_id   uuid,
      created_at    timestamptz NOT NULL DEFAULT now(),
      UNIQUE (org_id, source, external_id)
    );
    CREATE INDEX ON app.reviews (org_id, reviewed_at DESC);
    CREATE TABLE app.review_requests (
      id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      org_id      text NOT NULL,
      contact_id  uuid NOT NULL REFERENCES app.contacts(id),
      reason      text NOT NULL,                 -- booking:<id> | invoice:<id>
      channel     text,
      status      text NOT NULL CHECK (status IN ('sent','recorded','held','skipped')),
      note        text,
      created_at  timestamptz NOT NULL DEFAULT now(),
      UNIQUE (org_id, reason)
    );
    CREATE INDEX ON app.review_requests (org_id, contact_id, created_at DESC);
    """)
    for t in TABLES:
        op.execute(f"""
        ALTER TABLE app.{t} ENABLE ROW LEVEL SECURITY;
        ALTER TABLE app.{t} FORCE ROW LEVEL SECURITY;
        CREATE POLICY tenant_isolation ON app.{t}
          USING (org_id = current_setting('app.org_id', true)) WITH CHECK (org_id = current_setting('app.org_id', true));
        GRANT SELECT, INSERT, UPDATE, DELETE ON app.{t} TO agentry_app, agentry_system;
        """)
    op.execute("GRANT USAGE ON SEQUENCE app.watch_snapshots_id_seq TO agentry_app, agentry_system;")


def downgrade() -> None:
    op.execute("DROP TABLE app.review_requests; DROP TABLE app.reviews; DROP TABLE app.watch_snapshots; DROP TABLE app.watchers;")

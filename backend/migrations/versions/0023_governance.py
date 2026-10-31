"""Governance (ROADMAP-V2 §2.2): autonomy per action, daily limits, and a tamper-evident audit log.

    autonomy        per business and action: shadow (only recorded) · recommend (a Needs-you card) · auto_limited (on
                    its own, within limits) · auto; plus limits (max_per_day, quiet_hours)
    action_counts   how many times an action ran on its own today (for max_per_day)
    audit_log       each row gets prev_hash + hash = sha256(previous hash | the row), chained per business by a trigger,
                    so any edit or deletion breaks the chain and shows up in the check. The app roles can no longer
                    update or delete audit rows.

Revision ID: 0023
"""
from alembic import op

revision = "0023"
down_revision = "0022"
branch_labels = None
depends_on = None

ROW = ("concat_ws('|', {p}, r.org_id, r.actor_user_id, r.actor_type, r.action, r.target_type, r.target_id, r.metadata::text, r.ip, "
       "to_char(r.at at time zone 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS.US'))")


def upgrade() -> None:
    op.execute("""
    CREATE TABLE app.autonomy (
      org_id      text NOT NULL,
      action      text NOT NULL,
      level       text NOT NULL CHECK (level IN ('shadow','recommend','auto_limited','auto')),
      limits      jsonb NOT NULL DEFAULT '{}',
      updated_by  text,
      updated_at  timestamptz NOT NULL DEFAULT now(),
      PRIMARY KEY (org_id, action)
    );
    CREATE TABLE app.action_counts (
      org_id  text NOT NULL,
      action  text NOT NULL,
      day     date NOT NULL,
      n       int NOT NULL DEFAULT 0,
      PRIMARY KEY (org_id, action, day)
    );
    """)
    for t in ("autonomy", "action_counts"):
        op.execute(f"""
        ALTER TABLE app.{t} ENABLE ROW LEVEL SECURITY;
        ALTER TABLE app.{t} FORCE ROW LEVEL SECURITY;
        CREATE POLICY tenant_isolation ON app.{t}
          USING (org_id = current_setting('app.org_id', true)) WITH CHECK (org_id = current_setting('app.org_id', true));
        GRANT SELECT, INSERT, UPDATE, DELETE ON app.{t} TO agentry_app, agentry_system;
        """)
    row_new = ROW.replace("r.", "NEW.").replace("{p}", "NEW.prev_hash")
    row_bf = ROW.replace("{p}", "prev")
    op.execute(f"""
    ALTER TABLE app.audit_log ADD COLUMN prev_hash text, ADD COLUMN hash text;

    -- chain the rows that already exist, oldest first, per business
    DO $$
    DECLARE r record; prev text; cur_org text := '~none~';
    BEGIN
      FOR r IN SELECT * FROM app.audit_log ORDER BY coalesce(org_id, ''), id LOOP
        IF coalesce(r.org_id, '') IS DISTINCT FROM cur_org THEN prev := NULL; cur_org := coalesce(r.org_id, ''); END IF;
        UPDATE app.audit_log SET prev_hash = prev, hash = encode(sha256(convert_to({row_bf}, 'UTF8')), 'hex')
          WHERE id = r.id RETURNING hash INTO prev;
      END LOOP;
    END $$;

    CREATE FUNCTION app.chain_audit() RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path = app, pg_catalog AS $$
    BEGIN
      PERFORM pg_advisory_xact_lock(hashtext('audit:' || coalesce(NEW.org_id, '')));
      SELECT hash INTO NEW.prev_hash FROM app.audit_log WHERE org_id IS NOT DISTINCT FROM NEW.org_id ORDER BY id DESC LIMIT 1;
      NEW.hash := encode(sha256(convert_to({row_new}, 'UTF8')), 'hex');
      RETURN NEW;
    END $$;
    CREATE TRIGGER chain_audit BEFORE INSERT ON app.audit_log FOR EACH ROW EXECUTE FUNCTION app.chain_audit();

    -- one place to check a business's chain: the first row whose hash doesn't follow (NULL = intact)
    CREATE FUNCTION app.audit_chain_break(org text) RETURNS bigint LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path = app, pg_catalog AS $$
    DECLARE r record; prev text;
    BEGIN
      FOR r IN SELECT * FROM app.audit_log WHERE org_id IS NOT DISTINCT FROM org ORDER BY id LOOP
        IF r.prev_hash IS DISTINCT FROM prev OR r.hash IS DISTINCT FROM encode(sha256(convert_to({row_bf}, 'UTF8')), 'hex') THEN
          RETURN r.id;
        END IF;
        prev := r.hash;
      END LOOP;
      RETURN NULL;
    END $$;
    GRANT EXECUTE ON FUNCTION app.audit_chain_break(text) TO agentry_app, agentry_system;

    REVOKE UPDATE, DELETE ON app.audit_log FROM agentry_app, agentry_system;
    """)


def downgrade() -> None:
    op.execute("""
    GRANT UPDATE, DELETE ON app.audit_log TO agentry_app, agentry_system;
    DROP FUNCTION app.audit_chain_break(text); DROP TRIGGER chain_audit ON app.audit_log; DROP FUNCTION app.chain_audit();
    ALTER TABLE app.audit_log DROP COLUMN prev_hash, DROP COLUMN hash;
    DROP TABLE app.action_counts; DROP TABLE app.autonomy;
    """)

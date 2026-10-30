"""Auto-assign: every Needs-you card for a client (contact), or for an agent, goes to one chosen person.

Cards are created in many places, so the rule is applied by a trigger on app.approvals: a new card with nobody assigned
gets the person set for its contact, else the person set for its automation. A rule only covers the kinds of card its
person can handle (`resources`): a client given to Finance sends Finance that client's invoice cards, while the
client's emails stay with whoever handles conversations. Inbox routing (per mailbox, set in code before the insert)
and manual assignment are never overwritten.

Revision ID: 0017
"""
from alembic import op

revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
    CREATE TABLE app.card_routing (
      org_id      text NOT NULL,
      scope       text NOT NULL CHECK (scope IN ('contact','automation')),
      key         text NOT NULL,                 -- contact id, or automation key
      assign_to   text NOT NULL,                 -- user id
      resources   text[] NOT NULL,               -- kinds of card it covers: invoice, conversation
      set_by      text,
      created_at  timestamptz NOT NULL DEFAULT now(),
      PRIMARY KEY (org_id, scope, key)
    );
    ALTER TABLE app.card_routing ENABLE ROW LEVEL SECURITY;
    ALTER TABLE app.card_routing FORCE ROW LEVEL SECURITY;
    CREATE POLICY tenant_isolation ON app.card_routing
      USING (org_id = current_setting('app.org_id', true)) WITH CHECK (org_id = current_setting('app.org_id', true));
    GRANT SELECT, INSERT, UPDATE, DELETE ON app.card_routing TO agentry_app, agentry_system;

    -- Which contact a card is about: its invoice, its reminder sequence, or its conversation.
    CREATE FUNCTION app.card_contact(p jsonb, conv uuid) RETURNS uuid LANGUAGE sql STABLE AS $$
      SELECT coalesce(
        (SELECT contact_id FROM app.invoices WHERE id = (p->>'invoice_id')::uuid),
        (SELECT contact_id FROM app.sequence_enrollments WHERE id = (p->>'enrollment_id')::uuid),
        (SELECT contact_id FROM app.conversations WHERE id = conv),
        (p->>'contact_id')::uuid)
    $$;

    CREATE FUNCTION app.card_assignee(p jsonb, conv uuid, automation text) RETURNS text LANGUAGE sql STABLE AS $$
      SELECT coalesce(
        (SELECT assign_to FROM app.card_routing WHERE scope = 'contact' AND key = app.card_contact(p, conv)::text
           AND (CASE WHEN automation = 'invoice_follow_up' THEN 'invoice' ELSE 'conversation' END) = ANY (resources)),
        (SELECT assign_to FROM app.card_routing WHERE scope = 'automation' AND key = automation))
    $$;

    CREATE FUNCTION app.route_new_card() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      IF NEW.assigned_to IS NULL THEN
        NEW.assigned_to := app.card_assignee(NEW.payload, NEW.conversation_id, NEW.automation_key);
        IF NEW.assigned_to IS NOT NULL THEN
          NEW.assigned_by := 'rule';
        END IF;
      END IF;
      RETURN NEW;
    END $$;

    CREATE TRIGGER route_new_card BEFORE INSERT ON app.approvals FOR EACH ROW EXECUTE FUNCTION app.route_new_card();
    GRANT EXECUTE ON FUNCTION app.card_contact(jsonb, uuid), app.card_assignee(jsonb, uuid, text) TO agentry_app, agentry_system;
    """)


def downgrade() -> None:
    op.execute("""
    DROP TRIGGER route_new_card ON app.approvals;
    DROP FUNCTION app.route_new_card(); DROP FUNCTION app.card_assignee(jsonb, uuid, text); DROP FUNCTION app.card_contact(jsonb, uuid);
    DROP TABLE app.card_routing;
    """)

"""Appointment Concierge (ROADMAP-V2 9.3): reminders, confirm / reschedule by reply, waitlist, aftercare and recalls.

    bookings.concierge  what the concierge did and is waiting for: {reminded_at, day_of_at, awaiting: confirm|pick_slot,
                        offered: [iso times], aftercare_at, recall_sent_at, no_show_followup_at}
    bookings.cancel_reason
    waitlist            people who want an earlier slot for a service; a cancelled slot is offered to them, first yes wins

Revision ID: 0024
"""
from alembic import op

revision = "0024"
down_revision = "0023"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
    ALTER TABLE app.bookings ADD COLUMN concierge jsonb NOT NULL DEFAULT '{}', ADD COLUMN cancel_reason text;
    CREATE INDEX ON app.bookings (org_id, status, starts_at);

    CREATE TABLE app.waitlist (
      id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      org_id      text NOT NULL,
      contact_id  uuid NOT NULL REFERENCES app.contacts(id),
      service_id  uuid NOT NULL REFERENCES app.services(id),
      notes       text,
      status      text NOT NULL DEFAULT 'waiting' CHECK (status IN ('waiting','offered','booked','removed')),
      offered     jsonb,                              -- {starts_at, staff_id, booking_id (the cancelled one), at}
      created_by  text,
      created_at  timestamptz NOT NULL DEFAULT now()
    );
    ALTER TABLE app.waitlist ENABLE ROW LEVEL SECURITY;
    ALTER TABLE app.waitlist FORCE ROW LEVEL SECURITY;
    CREATE POLICY tenant_isolation ON app.waitlist
      USING (org_id = current_setting('app.org_id', true)) WITH CHECK (org_id = current_setting('app.org_id', true));
    GRANT SELECT, INSERT, UPDATE, DELETE ON app.waitlist TO agentry_app, agentry_system;
    """)


def downgrade() -> None:
    op.execute("DROP TABLE app.waitlist; ALTER TABLE app.bookings DROP COLUMN concierge, DROP COLUMN cancel_reason;")

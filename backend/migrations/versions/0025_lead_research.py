"""Lead Research & Meeting Prep (ROADMAP-V2 9.4).

    leads.research     what we found about a new lead's company: {status, domain, company, what_they_do, size,
                       decision_maker, likely_need, talking_points, questions, sources, at}
    bookings.brief     the one-page brief sent before the meeting: {title, body, sent_at, event_id}

Revision ID: 0025
"""
from alembic import op

revision = "0025"
down_revision = "0024"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
    ALTER TABLE app.leads ADD COLUMN research jsonb;
    ALTER TABLE app.bookings ADD COLUMN brief jsonb;
    """)


def downgrade() -> None:
    op.execute("ALTER TABLE app.leads DROP COLUMN research; ALTER TABLE app.bookings DROP COLUMN brief;")

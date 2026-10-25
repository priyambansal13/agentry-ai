"""Knowledge from uploaded files (PDF, Word, text, CSV) alongside FAQs, pasted text and websites.

Revision ID: 0008
"""
from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
    ALTER TABLE app.kb_documents DROP CONSTRAINT kb_documents_source_type_check;
    ALTER TABLE app.kb_documents ADD CONSTRAINT kb_documents_source_type_check CHECK (source_type IN ('url','faq','text','file'));
    """)


def downgrade() -> None:
    op.execute("""
    DELETE FROM app.kb_documents WHERE source_type = 'file';
    ALTER TABLE app.kb_documents DROP CONSTRAINT kb_documents_source_type_check;
    ALTER TABLE app.kb_documents ADD CONSTRAINT kb_documents_source_type_check CHECK (source_type IN ('url','faq','text'));
    """)

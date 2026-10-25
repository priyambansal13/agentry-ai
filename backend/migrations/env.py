"""Alembic runs as the schema owner (postgres in dev). Migrations are plain SQL: RLS policies are explicit."""
from alembic import context
from sqlalchemy import create_engine

from agentry.config import settings


def run_migrations_online() -> None:
    engine = create_engine(settings.migrate_database_url)
    with engine.connect() as connection:
        context.configure(connection=connection, version_table_schema="app")
        with context.begin_transaction():
            context.run_migrations()

run_migrations_online()

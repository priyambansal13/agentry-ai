"""Database access.

Two engines, two trust levels:
- app engine (role agentry_app, no BYPASSRLS): every tenant request runs in tenant_session(org_id), which sets
  app.org_id for the transaction. Row-level security filters every table by it; forgetting it returns no rows.
- system engine (role agentry_system, BYPASSRLS): workers, platform jobs and Agentry HQ only.
"""
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, create_async_engine

from agentry.config import settings

app_engine = create_async_engine(settings.app_database_url, pool_size=10, pool_pre_ping=True)
system_engine = create_async_engine(settings.system_database_url, pool_size=5, pool_pre_ping=True)


@asynccontextmanager
async def tenant_session(org_id: str) -> AsyncIterator[AsyncConnection]:
    if not org_id:
        raise ValueError("tenant_session needs an org_id")
    async with app_engine.begin() as conn:
        await conn.execute(text("select set_config('app.org_id', :org, true)"), {"org": org_id})
        yield conn


@asynccontextmanager
async def system_session() -> AsyncIterator[AsyncConnection]:
    async with system_engine.begin() as conn:
        yield conn

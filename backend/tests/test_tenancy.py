"""Row-level security: one client can never read or write another client's data."""
import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from agentry.db import app_engine, tenant_session


async def test_each_org_sees_only_its_own_contacts(orgs):
    async with tenant_session(orgs["sharma-digital"]) as conn:
        sharma = {r.org_id for r in (await conn.execute(text("select org_id from app.contacts"))).all()}
    async with tenant_session(orgs["smilecraft"]) as conn:
        smile = {r.org_id for r in (await conn.execute(text("select org_id from app.contacts"))).all()}
    assert sharma == {orgs["sharma-digital"]}
    assert smile == {orgs["smilecraft"]}


async def test_no_org_context_sees_nothing():
    async with app_engine.begin() as conn:
        for table in ("contacts", "events", "metrics_daily", "audit_log", "automation_instances"):
            n = (await conn.execute(text(f"select count(*) from app.{table}"))).scalar_one()
            assert n == 0, f"app role saw {n} rows in {table} without an org context"


async def test_cannot_write_into_another_org(orgs):
    with pytest.raises(DBAPIError, match="row-level security"):
        async with tenant_session(orgs["sharma-digital"]) as conn:
            await conn.execute(text("insert into app.contacts (org_id, name) values (:o, 'intruder')"),
                               {"o": orgs["smilecraft"]})


async def test_cannot_move_a_row_to_another_org(orgs):
    with pytest.raises(DBAPIError, match="row-level security"):
        async with tenant_session(orgs["sharma-digital"]) as conn:
            await conn.execute(text("update app.contacts set org_id = :o"), {"o": orgs["smilecraft"]})


async def test_app_role_cannot_read_auth_secrets():
    async with app_engine.begin() as conn:
        for table in ("auth.jwks", "auth.account", "auth.session"):
            with pytest.raises(DBAPIError, match="permission denied"):
                async with conn.begin_nested():
                    await conn.execute(text(f"select 1 from {table} limit 1"))


async def test_audit_log_is_append_only_for_the_api(orgs):
    with pytest.raises(DBAPIError, match="permission denied"):
        async with tenant_session(orgs["sharma-digital"]) as conn:
            await conn.execute(text("delete from app.audit_log"))

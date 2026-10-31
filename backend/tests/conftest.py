"""Integration tests against the local Postgres (docker compose up) with seeded demo data
(pnpm seed:auth + uv run agentry seed)."""
import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import create_engine, text

from agentry import auth as auth_mod
from agentry.api.main import app
from agentry.config import settings
from agentry.db import system_session


@pytest.fixture(autouse=True)
def mock_completion_models(monkeypatch):
    """Tests never call paid or rate-limited models: every tier runs in mock mode (scripted where it matters), including
    embeddings, so the suite doesn't depend on a provider's daily quota. Tests that search knowledge index it themselves."""
    from agentry.config import settings
    for tier in ("fast", "writer", "conversation", "vision", "embed"):
        monkeypatch.setattr(settings, f"model_{tier}", None)


@pytest.fixture(autouse=True)
def daytime_for_governance(monkeypatch):
    """Tests don't depend on the clock: automatic sends aren't held for quiet hours (tests/test_governance.py checks
    quiet hours itself, with fixed times)."""
    from agentry import governance
    monkeypatch.setattr(governance, "_quiet", lambda now, tz: False)


@pytest.fixture(autouse=True)
def local_mailbox(monkeypatch):
    """Tests never send real email, whatever SMTP .env points at: everything goes to the local Mailpit."""
    from agentry.config import settings
    for k, v in {"smtp_host": "localhost", "smtp_port": 51025, "smtp_user": None, "smtp_password": None,
                 "smtp_starttls": None, "mail_from": "Agentry <hello@agentry.dev>"}.items():
        monkeypatch.setattr(settings, k, v)


@pytest.fixture(scope="session", autouse=True)
def dbos_for_tests():
    """An in-process DBOS with its own state schema (dbos_test), so tests never share queues or schedules with a
    running worker."""
    from dbos import DBOS, DBOSConfig

    from agentry.automations import load_all
    from agentry.config import settings

    load_all()
    DBOS(config=DBOSConfig(name="agentry-test", system_database_url=settings.dbos_database_url,
                           dbos_system_schema="dbos_test"))
    DBOS.launch()
    yield
    DBOS.destroy()


@pytest.fixture(scope="session", autouse=True)
async def cleanup_test_rows():
    """Tests create conversations with external_ref 'test-%'; remove them (and their leads, contacts, events) after.
    Events the tests emitted are marked handled, so a dev worker started later doesn't process events for test data."""
    async with system_session() as conn:
        started = (await conn.execute(text("select max(id) from app.events"))).scalar_one() or 0
    yield
    async with system_session() as conn:
        await conn.execute(text("update app.events set dispatched_at = now() where dispatched_at is null and id > :s"), {"s": started})
        await conn.execute(text("""
            with convs as (select id from app.conversations where external_ref like 'test-%'),
                 lead_contacts as (select contact_id from app.leads where conversation_id in (select id from convs)),
                 del_leads as (delete from app.leads where conversation_id in (select id from convs) returning id),
                 del_events as (delete from app.events where payload->>'conversation_id' in (select id::text from convs)
                                or payload->>'lead_id' in (select id::text from del_leads)),
                 del_convs as (delete from app.conversations where id in (select id from convs))
            delete from app.contacts where id in (select contact_id from lead_contacts) and source in ('email', 'inbox', 'web_chat')"""))


TABLES = ["statement_lines", "statements", "outcomes", "pricing_plans", "notification_preferences", "autonomy", "action_counts", "agent_runs", "notifications", "notification_rules", "telegram_links", "approvals", "content_posts", "content_moments", "content_sources", "brand_kits", "messages", "bookings", "sequence_enrollments", "prospects", "prospect_companies", "campaigns", "sequences", "payments", "invoices",
          "lead_sources", "leads", "consents", "suppressions", "conversations", "events", "connections", "automation_instances",
          "audit_log", "llm_calls", "kb_chunks", "kb_documents", "staff", "services", "onboarding_progress", "metrics_daily"]


@pytest.fixture
async def org():
    """A fresh client organisation with invoice follow-up, reactivation and speed-to-lead live; removed afterwards."""
    owner = create_engine(settings.migrate_database_url)
    oid = str(uuid.uuid4())
    with owner.begin() as c:
        c.execute(text("""insert into auth.organization (id, name, slug, "createdAt") values (:i, 'Test Co', :s, now())"""),
                  {"i": oid, "s": f"test-co-{oid[:8]}"})
        c.execute(text("""insert into app.org_settings (org_id, status, country, timezone, currency, persona)
            values (:i, 'live', 'IN', 'Asia/Kolkata', 'INR', '{"name": "Ava", "signoff": "Team Test Co"}')"""), {"i": oid})
        for k in ("invoice_follow_up", "lead_reactivation", "speed_to_lead"):
            c.execute(text("insert into app.automation_instances (org_id, template_key, status) values (:i, :k, 'live')"), {"i": oid, "k": k})
    yield oid
    with owner.begin() as c:
        c.execute(text("update app.contacts set merged_into = null where org_id = :i"), {"i": oid})
        for t in [*TABLES, "contacts", "org_settings"]:
            c.execute(text(f"delete from app.{t} where org_id = :i"), {"i": oid})
        c.execute(text("delete from auth.organization where id = :i"), {"i": oid})



@pytest.fixture(scope="session")
async def orgs() -> dict[str, str]:
    async with system_session() as conn:
        return {r.slug: r.id for r in (await conn.execute(text("select id, slug from auth.organization"))).all()}


@pytest.fixture(scope="session")
async def users() -> dict[str, str]:
    """email -> user id. "admin@agentry.dev" always means an Agentry admin (platform role admin), whatever real address
    the admin account has been given."""
    async with system_session() as conn:
        rows = (await conn.execute(text('select id, email, role from auth."user" order by "createdAt"'))).all()
    out = {r.email: r.id for r in rows}
    admin = next((r.id for r in rows if r.email == "admin@agentry.dev"), None) or next((r.id for r in rows if r.role == "admin"), None)
    if admin:
        out["admin@agentry.dev"] = admin
    return out


@pytest.fixture
def login(monkeypatch, users):
    """Bypass JWT signature checks: the token string is the user's email. Membership is still read from the DB."""
    def _decode(token: str) -> dict:
        return {"sub": users[token], "email": token, "name": token,
                "platform_role": "admin" if token == "admin@agentry.dev" else "user"}
    monkeypatch.setattr(auth_mod, "_decode", _decode)
    return lambda email: {"Authorization": f"Bearer {email}"}


@pytest.fixture
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


ROLES = ("owner", "manager", "staff", "finance", "viewer")


@pytest.fixture
async def team_org(client, monkeypatch, users):
    """Factory: a client provisioned from HQ with the given automations and one member per role.
    Returns (org_id, headers) where headers[role] signs in as that member ("agentry" = Agentry staff)."""
    owner_db = create_engine(settings.migrate_database_url)
    made: list[tuple[str, list[str]]] = []
    ids = dict(users)

    def _decode(token: str) -> dict:
        return {"sub": ids[token], "email": token, "name": token,
                "platform_role": "admin" if token == "admin@agentry.dev" else "user"}
    monkeypatch.setattr(auth_mod, "_decode", _decode)

    async def make(automations: list[str], live: bool = True):
        oid, tag = str(uuid.uuid4()), uuid.uuid4().hex[:6]
        emails = {r: f"{r}-{tag}@team.example" for r in ROLES}
        with owner_db.begin() as c:
            c.execute(text("""insert into auth.organization (id, name, slug, "createdAt") values (:i, 'Team Test Co', :s, now())"""),
                      {"i": oid, "s": f"team-{tag}"})
            for role, email in emails.items():
                uid = str(uuid.uuid4())
                ids[email] = uid
                c.execute(text("""insert into auth."user" (id, name, email, "emailVerified", role, "createdAt", "updatedAt")
                                  values (:u, :n, :e, true, 'user', now(), now())"""), {"u": uid, "n": role.title(), "e": email})
                c.execute(text("""insert into auth.member (id, "organizationId", "userId", role, "createdAt") values (:i, :o, :u, :r, now())"""),
                          {"i": str(uuid.uuid4()), "o": oid, "u": uid, "r": role})
        made.append((oid, list(emails.values())))
        staff = {"Authorization": "Bearer admin@agentry.dev"}
        r = await client.post("/hq/clients", headers=staff, json={"org_id": oid, "automations": automations})
        assert r.status_code == 201, r.text
        if live:
            with owner_db.begin() as c:
                c.execute(text("update app.org_settings set status = 'live' where org_id = :o"), {"o": oid})
                c.execute(text("update app.automation_instances set status = 'live' where org_id = :o"), {"o": oid})
        headers = {r: {"Authorization": f"Bearer {e}", "X-Org-Id": oid} for r, e in emails.items()}
        headers["agentry"] = staff | {"X-Org-Id": oid}
        return oid, headers

    yield make
    with owner_db.begin() as c:
        for oid, emails in made:
            c.execute(text("update app.contacts set merged_into = null where org_id = :i"), {"i": oid})
            for t in [*TABLES, "contacts", "org_settings"]:
                c.execute(text(f"delete from app.{t} where org_id = :i"), {"i": oid})
            c.execute(text("""delete from auth.member where "organizationId" = :i"""), {"i": oid})
            c.execute(text("delete from auth.organization where id = :i"), {"i": oid})
            c.execute(text("""delete from auth."user" where email = any(:e)"""), {"e": emails})


def expect(statuses: dict[str, int], **by_role: int) -> None:
    """Compare {role: status} with the expected matrix; one assertion error listing every mismatch."""
    wrong = {r: (statuses[r], want) for r, want in by_role.items() if statuses[r] != want}
    assert not wrong, f"role -> (got, expected): {wrong}"


@pytest.fixture
async def faqs():
    """Index FAQs into an organisation for one test (offline embeddings); removed afterwards."""
    from agentry.db import tenant_session
    from agentry.knowledge import add_faqs
    added: list[tuple[str, list[str]]] = []

    async def add(org_id: str, items: list[dict]) -> None:
        await add_faqs(org_id, items)
        added.append((org_id, [i["q"] for i in items]))

    yield add
    for org_id, titles in added:
        async with tenant_session(org_id) as conn:
            await conn.execute(text("delete from app.kb_documents where title = any(:t) and created_at > now() - interval '1 hour'"),
                               {"t": titles})

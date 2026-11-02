"""Catalogue & quotes (ROADMAP-V3 A3): answers from the catalogue only, quotes priced by code, sent, followed up."""
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text

from agentry.agents.runtime import run_turn, setup_checkpointer
from agentry.automations import catalog_quotes as cq
from agentry.db import tenant_session
from agentry.leads import resolve_contact
from agentry.llm.gateway import LLMResult

CATALOGUE = (b"Code,Product,Category,Unit,Price,GST %,Stock,Min qty,Description\n"
             b"AC-15,Split AC 1.5 ton 5 star,AC,pc,38990,28,4,1,Inverter split AC with copper coil\n"
             b"AC-INST,AC installation,Service,job,1500,18,,1,Standard wall installation\n"
             b"PIPE-3M,Copper pipe 3 m,Parts,set,2200,18,0,1,\n")


@pytest.fixture(scope="module", autouse=True)
async def checkpointer():
    await setup_checkpointer()


def result(text_: str = "", calls: list[dict] | None = None) -> LLMResult:
    return LLMResult(text_, None, "scripted/model", False, 10, 5, 0.0, 1, [{"id": f"call_{i}", **c} for i, c in enumerate(calls or [])])


class Script:
    def __init__(self, steps):
        self.steps, self.seen = list(steps), []

    async def __call__(self, tier, messages, **kw):
        self.seen.append([m for m in messages if m["role"] == "tool"])
        step = self.steps.pop(0)
        return step(messages) if callable(step) else step


async def _setup(client, team_org, live=True):
    oid, h = await team_org(["whatsapp_assistant", "catalog_quotes"], live=live)
    r = await client.post("/org/quotes/products/import", headers=h["manager"], files={"file": ("products.csv", CATALOGUE, "text/csv")})
    assert r.json() == {"imported": 3, "skipped_rows": []}
    async with tenant_session(oid) as conn:
        k = await resolve_contact(conn, oid, name="Neha Kapoor", phone="+919810000041", source="whatsapp")
        conv = str((await conn.execute(text("""insert into app.conversations (org_id, channel, automation_key, contact_id, external_ref)
            values (:o, 'whatsapp', 'whatsapp_assistant', :k, 'wa:919810000041') returning id"""), {"o": oid, "k": k})).scalar_one())
    return oid, h, conv


async def test_answers_and_a_quote_from_the_chat(client, team_org, monkeypatch):
    from agentry import outbound
    oid, h, conv = await _setup(client, team_org)
    sent = []

    async def fake_reach(conn, org_id, who, body, **kw):
        sent.append(body)
        return {"status": "sent", "channel": "whatsapp"}
    monkeypatch.setattr(outbound, "reach_contact", fake_reach)
    script = Script([result(calls=[{"name": "search_catalog", "arguments": {"query": "1.5 ton split AC"}}]),
                     lambda m: result("The 1.5 ton 5 star split AC is ₹38,990 before GST, and we have it in stock.")])
    await run_turn(oid, conv, "Price of 1.5 ton split AC?", llm=script, channel="whatsapp", source="whatsapp")
    seen = script.seen[1][0]["content"]
    assert "AC-15" in seen and "38990" in seen and "before GST" in seen
    script = Script([result(calls=[{"name": "make_quote", "arguments": {"items": [{"code": "AC-15", "qty": 2}, {"code": "ac-inst", "qty": 2}],
                                                                       "name": "Neha Kapoor", "phone": "+919810000041"}}]),
                     lambda m: result("Done! I've sent quote Q-2026-0001 to you here.")])
    await run_turn(oid, conv, "Send me a quote for 2 with installation", llm=script, channel="whatsapp", source="whatsapp")
    q = (await client.get("/org/quotes", headers=h["staff"])).json()["items"][0]
    # prices from the catalogue: 2 x 38990 @28% + 2 x 1500 @18% = 77980 + 21834.40 + 3000 + 540
    assert q["number"].startswith("Q-") and float(q["total"]) == 103354.40 and q["status"] == "sent" and q["source"] == "agent"
    assert "103,354.40" in sent[0] and "/public/quotes/" in sent[0]
    d = (await client.get(f"/org/quotes/{q['id']}", headers=h["finance"])).json()
    link_path = d["link"].split("8801")[-1] if "8801" in d["link"] else "/public/quotes/" + d["link"].rsplit("/", 1)[-1]
    pdf = await client.get(link_path)
    assert pdf.status_code == 200 and pdf.content[:4] == b"%PDF"
    assert (await client.get("/public/quotes/not-a-real-token-at-all-xyz.pdf")).status_code == 404
    # follow-ups on days 2 and 5, then expiry
    sent_at = datetime.now(UTC)
    assert await cq.follow_ups(oid, sent_at + timedelta(days=1)) == 0
    assert await cq.follow_ups(oid, sent_at + timedelta(days=2, hours=1)) == 1
    assert await cq.follow_ups(oid, sent_at + timedelta(days=5, hours=1)) == 1
    assert await cq.follow_ups(oid, sent_at + timedelta(days=6)) == 0
    assert (await client.post(f"/org/quotes/{q['id']}/outcome", headers=h["staff"], json={"outcome": "won"})).json()["status"] == "won"
    assert (await client.post(f"/org/quotes/{q['id']}/outcome", headers=h["staff"], json={"outcome": "lost"})).status_code == 409
    assert (await client.post(f"/org/quotes/{q['id']}/outcome", headers=h["finance"], json={"outcome": "won"})).status_code == 403
    assert (await client.get("/org/quotes", headers=h["owner"])).json()["stats"]["won_value"] == 103354.40


async def test_quote_checks_and_approval_mode(client, team_org):
    oid, h, conv = await _setup(client, team_org, live=False)
    async with tenant_session(oid) as conn:
        await conn.execute(text("update app.automation_instances set status = 'approval_mode'"))
    r = await cq.quote_from_chat(oid, conv, {"items": [{"code": "NOPE", "qty": 1}], "name": "Neha"}, "whatsapp")
    assert "isn't in the catalogue" in r["error"]  # never a made-up product or price
    r = await cq.quote_from_chat(oid, conv, {"items": [{"code": "AC-15", "qty": 1}], "name": "Neha Kapoor", "phone": "+919810000041"}, "whatsapp")
    assert "team will send" in r["tell_customer"]
    async with tenant_session(oid) as conn:
        card = (await conn.execute(text("select title, payload from app.approvals where automation_key = 'catalog_quotes'"))).one()
        status = (await conn.execute(text("select status from app.quotes"))).scalar_one()
    assert card.title.startswith("Send quote Q-") and status == "draft"
    # manual quote from the portal, prices inclusive of GST
    async with tenant_session(oid) as conn:
        await conn.execute(text("update app.automation_instances set config = config || '{\"prices_include_gst\": true}'"))
    r = await client.post("/org/quotes", headers=h["owner"], json={"customer": "Walk-in", "items": [{"code": "AC-INST", "qty": 1}]})
    assert r.status_code == 201 and r.json()["total"] == 1500.0  # 1271.19 + 228.81
    assert (await client.post("/org/quotes", headers=h["owner"], json={"customer": "X Y", "items": [{"code": "AC-15", "qty": 0.5}]})).status_code == 422


async def test_catalogue_search_only_finds_real_products(team_org, client):
    oid, _h, _conv = await _setup(client, team_org)
    r = await cq.search_catalog(oid, "copper pipe")
    assert r["products"][0]["code"] == "PIPE-3M" and r["products"][0]["in_stock"] is False
    assert (await cq.search_catalog(oid, "washing machine"))["found"] is False

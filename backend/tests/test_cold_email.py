"""Cold email 5.1-5.3: the prospect pipeline on the mock clinic list (reference funnel 50 -> 49 -> 8), fact-checked
first lines, review in the portal and who may do what."""
import io

from conftest import expect
from sqlalchemy import text

from agentry.automations.cold_email import pipeline, providers, research
from agentry.db import tenant_session

ALL = ("owner", "manager", "staff", "finance", "viewer", "agentry")
SEARCH = {"name": "Pune dentists", "query": "dental clinic", "city": "Pune", "limit": 50, "min_rating": 4.0, "min_reviews": 20}


async def seed_known(oid: str) -> None:
    """SmileCraft is already a client; one dentist asked never to be emailed."""
    async with tenant_session(oid) as conn:
        await conn.execute(text("""insert into app.contacts (org_id, name, email, email_norm, source)
            values (:o, 'Neha (SmileCraft)', 'neha@smilecraft.example', 'neha@smilecraft.example', 'test')"""), {"o": oid})
        for a in providers.mock_suppressed():
            await conn.execute(text("insert into app.suppressions (org_id, address, channel, reason) values (:o, :a, 'email', 'opt_out')"),
                               {"o": oid, "a": a})


async def built(client, h, oid: str, body: dict = SEARCH) -> str:
    r = await client.post("/org/cold-email/campaigns", headers=h["owner"], json=body)
    assert r.status_code == 201, r.text
    cid = r.json()["id"]
    assert await pipeline.build_list(oid, cid) == "built"
    return cid


def counts(campaign: dict) -> dict:
    return {s["key"]: s["count"] for s in campaign["funnel"]["steps"]}


async def test_reference_funnel_and_grounded_lines(client, team_org):
    oid, h = await team_org(["cold_email"])
    await seed_known(oid)
    cid = await built(client, h, oid)
    c = (await client.get(f"/org/cold-email/campaigns/{cid}", headers=h["owner"])).json()
    assert c["build_status"] == "built" and c["stats"] == {"total": 50, "processed": 50}
    assert counts(c) == {"found": 50, "website": 49, "fits": 46, "new": 45, "decision_maker": 15, "verified": 8, "ready": 8}
    dropped = {d["reason"]: d["count"] for d in c["funnel"]["dropped"]}
    assert dropped == {"only a generic inbox (info@...)": 26, "couldn't read their website": 3, "email is invalid": 3,
                       "email can't be confirmed (catch-all domain)": 2, "rating below 4.0": 2, "fewer than 20 reviews": 1,
                       "no website": 1, "already a client, lead or earlier prospect": 1, "on the do-not-contact list": 1,
                       "email couldn't be checked": 1, "guessed address couldn't be verified": 1}
    assert sum(dropped.values()) + 8 == 50
    items = (await client.get(f"/org/cold-email/campaigns/{cid}/prospects", headers=h["owner"])).json()["items"]
    assert len(items) == 8 and {p["email_source"] for p in items} == {"site", "finder", "pattern"}
    for p in items:  # every first line is based on a stored fact from that business's own website
        snip = next(s for s in p["snippets"] if s["n"] == p["line_snippet"])
        assert snip["url"].startswith(p["website"]) and research.word_check(p["first_line"], snip["text"], p["company"])[0]
        assert p["review"] == "pending" and p["fact_check"]["ok"] and p["role"]
        assert not research.is_generic(p["email"])


async def test_a_planted_false_claim_is_caught(client, team_org, monkeypatch):
    oid, h = await team_org(["cold_email"])
    real = research.complete

    async def lying_writer(tier, messages, **kw):
        if kw.get("prompt_key") == "cold_email_first_line":
            from types import SimpleNamespace
            return SimpleNamespace(data={"line": "Congratulations on being named Pune's best dental clinic of 2024.", "snippet": 1},
                                   text="", mock=False, model="test/model")
        return await real(tier, messages, **kw)
    monkeypatch.setattr(research, "complete", lying_writer)
    cid = await built(client, h, oid)
    c = (await client.get(f"/org/cold-email/campaigns/{cid}", headers=h["owner"])).json()
    assert counts(c)["verified"] == 8 and counts(c)["ready"] == 0
    assert c["funnel"]["review"]["needs_attention"] == counts(c)["verified"]
    p = (await client.get(f"/org/cold-email/campaigns/{cid}/prospects?review=needs_attention", headers=h["owner"])).json()["items"][0]
    assert p["fact_check"]["ok"] is False and p["fact_check"]["attempts"] == 2 and "2024" in p["fact_check"]["reason"]
    # a person must fix the line before it can be approved
    r = await client.post(f"/org/cold-email/prospects/{p['id']}", headers=h["manager"], json={"action": "approve"})
    assert r.status_code == 409
    fixed = "Read that you were one of the first clinics in your area to switch to digital X-rays."
    r = await client.post(f"/org/cold-email/prospects/{p['id']}", headers=h["manager"], json={"action": "approve", "first_line": fixed})
    assert r.json() == {"id": p["id"], "review": "approved", "edited": True}
    assert (await client.post("/org/cold-email/campaigns/" + cid + "/approve-ready", headers=h["owner"])).json() == {"approved": 0}


async def test_suppressed_dentist_without_seed_is_dropped_anyway(client, team_org):
    """Unseeded, SmileCraft only has a generic inbox and the do-not-contact dentist's address fails verification,
    so the reference count still holds."""
    oid, h = await team_org(["cold_email"])
    cid = await built(client, h, oid)
    c = counts((await client.get(f"/org/cold-email/campaigns/{cid}", headers=h["owner"])).json())
    assert c["found"] == 50 and c["website"] == 49 and c["new"] == 46 and c["decision_maker"] == 16 and c["verified"] == 8


async def test_roles_review_bulk_and_export(client, team_org):
    oid, h = await team_org(["cold_email"])
    got = {r: (await client.get("/org/cold-email/campaigns", headers=h[r])).status_code for r in ALL}
    expect(got, owner=200, manager=200, staff=200, finance=403, viewer=403, agentry=200)
    got = {r: (await client.post("/org/cold-email/campaigns", headers=h[r], json=SEARCH | {"name": f"List {r}"})).status_code
           for r in ("staff", "finance", "viewer")}
    expect(got, staff=403, finance=403, viewer=403)
    cid = await built(client, h, oid)
    items = (await client.get(f"/org/cold-email/campaigns/{cid}/prospects", headers=h["staff"])).json()["items"]
    one, two = items[0]["id"], items[1]["id"]
    got = {r: (await client.post(f"/org/cold-email/prospects/{one}", headers=h[r], json={"action": "drop"})).status_code for r in ALL}
    expect(got, owner=200, manager=200, staff=403, finance=403, viewer=403, agentry=200)
    edited = "Read that your clinic keeps a written treatment plan with prices for every patient before starting."
    r = (await client.post(f"/org/cold-email/prospects/{two}", headers=h["owner"], json={"action": "approve", "first_line": edited})).json()
    assert r["edited"] is True
    assert (await client.post(f"/org/cold-email/campaigns/{cid}/approve-ready", headers=h["owner"])).json() == {"approved": 6}
    c = (await client.get(f"/org/cold-email/campaigns/{cid}", headers=h["owner"])).json()
    assert c["funnel"]["review"] == {"pending": 0, "needs_attention": 0, "approved": 7, "dropped": 1}
    got = {r: (await client.get(f"/org/cold-email/campaigns/{cid}/export.csv", headers=h[r])).status_code for r in ALL}
    expect(got, owner=200, manager=200, staff=403, finance=403, viewer=403, agentry=200)
    sheet = (await client.get(f"/org/cold-email/campaigns/{cid}/export.csv?review=approved", headers=h["owner"])).text
    lines = sheet.strip().splitlines()
    assert lines[0].startswith("Company,Website") and len(lines) == 8 and edited in sheet
    async with tenant_session(oid) as conn:
        acts = (await conn.execute(text("select action from app.audit_log where action like 'cold_email.%'"))).scalars().all()
    assert {"cold_email.campaign_created", "cold_email.prospect_dropped", "cold_email.prospect_approved", "cold_email.bulk_approved"} <= set(acts)


async def test_second_campaign_skips_businesses_already_prospected(client, team_org):
    oid, h = await team_org(["cold_email"])
    await built(client, h, oid)
    again = await built(client, h, oid, SEARCH | {"name": "Pune dentists again"})
    c = counts((await client.get(f"/org/cold-email/campaigns/{again}", headers=h["owner"])).json())
    assert c["fits"] == 46 and c["new"] == 0


async def test_csv_list_and_eu_filter(client, team_org):
    oid, h = await team_org(["cold_email"])
    rows = providers._mock_rows()
    site = next(r for r in rows if r["expect"] == "site_email_valid")
    csv_text = ("Company,Website,Rating,Reviews\n"
                f"{site['name']},{site['website']},4.8,210\n"
                "No Site Dental,,4.5,90\n"
                "Zahnarzt Berlin,https://zahnarzt-berlin.de,4.9,300\n")
    files = {"file": ("list.csv", io.BytesIO(csv_text.encode()), "text/csv")}
    r = await client.post("/org/cold-email/campaigns/csv", headers=h["manager"], files=files, data={"name": "From Apollo"})
    assert r.status_code == 201 and r.json()["businesses"] == 3, r.text
    assert await pipeline.build_list(oid, r.json()["id"]) == "built"
    c = (await client.get(f"/org/cold-email/campaigns/{r.json()['id']}", headers=h["owner"])).json()
    assert counts(c)["ready"] == 1
    assert {d["reason"] for d in c["funnel"]["dropped"]} == {"no website", "EU/UK business (off for this campaign)"}
    bad = {"file": ("x.csv", io.BytesIO(b"Phone\n123\n"), "text/csv")}
    assert (await client.post("/org/cold-email/campaigns/csv", headers=h["owner"], files=bad, data={"name": "Bad"})).status_code == 422


async def test_hidden_without_cold_email_and_reactivation_list_unchanged(client, team_org):
    oid, h = await team_org(["lead_reactivation"])
    assert (await client.get("/org/cold-email/campaigns", headers=h["owner"])).status_code == 404
    both, hb = await team_org(["lead_reactivation", "cold_email"])
    await client.post("/org/cold-email/campaigns", headers=hb["owner"], json=SEARCH)
    assert (await client.get("/org/campaigns", headers=hb["owner"])).json()["items"] == []
    assert oid and both


def test_decision_maker_rules():
    pages = [providers.SitePage("https://x.example/team", "Team", "Our team\n\nDr. Asha Rao, Founder — asha@x.example\n\n"
                                "Priya Nair, Front desk — frontdesk@x.example")]
    people = research.people_by_pattern(pages)
    assert [(p.name, p.decides) for p in people] == [("Asha Rao", True), ("Priya Nair", False)]
    snips = research.snippets([providers.SitePage("https://x.example/about", "About",
                               "Founded in 2004, X Dental has looked after more than 3,000 families in Baner.\n\n"
                               "Call 98100 00000 to book.\n\nWe were one of the first clinics in Baner to use digital X-rays.")])
    assert [s["text"][:12] for s in snips] == ["Founded in 2", "We were one "]
    line = research.heuristic_line("X Dental", snips[1])
    assert line == "Read on your website that you were one of the first clinics in Baner to use digital X-rays."
    assert research.word_check(line, snips[1]["text"])[0]
    assert not research.word_check("Congrats on 25 years in Baner.", snips[1]["text"])[0]
    assert not research.word_check("Read that you are the best clinic in Baner to use digital X-rays.", snips[1]["text"])[0]

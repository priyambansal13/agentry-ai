"""Review management + Watchers: reviews are classified, bad ones alert at once, good ones may be answered on their own
(governance), the rest wait for a person; review requests go once, never to unhappy reviewers; watchers notice real
changes (not timestamps), prices past the threshold, stock, and stop after repeated failures."""
from datetime import UTC, datetime

from conftest import expect
from sqlalchemy import text

from agentry import watchers
from agentry.automations import reviews as rv
from agentry.db import tenant_session
from agentry.leads import resolve_contact

ALL = ("owner", "manager", "staff", "finance", "viewer", "agentry")


async def events(oid: str, kind: str) -> list[dict]:
    async with tenant_session(oid) as conn:
        return list((await conn.execute(text("select payload from app.events where type = :t order by id"), {"t": kind})).scalars())


async def test_sync_classifies_alerts_and_answers_the_good_ones(client, team_org):
    oid, h = await team_org(["reviews"])  # live: replies to 4-5 star reviews may go out on their own (within limits)
    assert await rv.sync(oid) == 8
    assert await rv.sync(oid) == 0  # nothing new the second time
    async with tenant_session(oid) as conn:
        rows = {r.author: r for r in (await conn.execute(text("select author, rating, sentiment, topics, urgent, reply_status, reply from app.reviews"))).all()}
        cards = (await conn.execute(text("select title, payload from app.approvals where automation_key = 'reviews' order by title"))).all()
    assert rows["Sana Shaikh"].urgent and rows["Sana Shaikh"].sentiment == "negative"  # 1 star + consumer forum
    assert "waiting time" in rows["Rohit Sharma"].topics and rows["Rohit Sharma"].reply_status == "drafted"
    assert {a for a, r in rows.items() if r.reply_status == "posted"} == {"Ananya Kulkarni", "Meera Joshi", "Vikram Patil", "Priya Nair", "Arjun Rao"}
    assert rows["Ananya Kulkarni"].reply.startswith("Thank you so much, Ananya!")
    assert [c.title for c in cards] == ["Reply to Karan Mehta's ★★★ review", "Reply to Rohit Sharma's ★★ review", "Reply to Sana Shaikh's ★ review"]
    assert [c.payload.get("urgent") for c in cards] == [None, True, True]
    assert [(e["author"], e["rating"]) for e in await events(oid, "review.negative")] == [("Rohit Sharma", 2), ("Sana Shaikh", 1)]
    got = {r: (await client.get("/org/reviews", headers=h[r])).status_code for r in ALL}
    expect(got, owner=200, manager=200, staff=200, finance=403, viewer=403, agentry=200)
    d = (await client.get("/org/reviews?filter=unanswered", headers=h["staff"])).json()
    assert len(d["items"]) == 3 and d["total"] == 8 and d["sample"] is True and d["last30"]["count"] == 7


async def test_approval_mode_cards_and_replying(client, team_org):
    oid, h = await team_org(["reviews"])
    async with tenant_session(oid) as conn:
        await conn.execute(text("update app.automation_instances set status = 'approval_mode'"))
    await rv.sync(oid)
    async with tenant_session(oid) as conn:
        assert (await conn.execute(text("select count(*) from app.reviews where reply_status = 'posted'"))).scalar_one() == 0  # nothing on its own
        card, rid = (await conn.execute(text("""select a.id::text, r.id::text from app.approvals a join app.reviews r on r.approval_id = a.id
            where r.author = 'Vikram Patil'"""))).one()
    r = await client.post(f"/org/approvals/{card}", headers=h["staff"], json={"action": "approve", "body": "Thanks Vikram, glad the plan helped!"})
    assert r.status_code == 200, r.text
    assert await rv.review_card_step(oid, card, "edited") == "posted"
    async with tenant_session(oid) as conn:
        assert tuple((await conn.execute(text("select reply_status, reply from app.reviews where id = cast(:i as uuid)"), {"i": rid})).one()) \
            == ("posted", "Thanks Vikram, glad the plan helped!")
        other = (await conn.execute(text("select id::text from app.reviews where author = 'Rohit Sharma'"))).scalar_one()
    assert (await client.put(f"/org/reviews/{other}", headers=h["viewer"], json={"action": "post"})).status_code == 403
    assert (await client.put(f"/org/reviews/{other}", headers=h["manager"], json={"action": "post", "body": "Sorry Rohit, please call us."})).status_code == 200
    assert (await client.put(f"/org/reviews/{other}", headers=h["manager"], json={"action": "post"})).status_code == 409
    async with tenant_session(oid) as conn:
        assert (await conn.execute(text("""select a.status from app.approvals a join app.reviews r on r.approval_id = a.id
            where r.id = cast(:i as uuid)"""), {"i": other})).scalar_one() == "resolved"


async def test_review_requests_once_and_never_to_unhappy_reviewers(team_org):
    oid, _h = await team_org(["reviews"])
    async with tenant_session(oid) as conn:
        happy = await resolve_contact(conn, oid, name="Neel Shah", email="neel@patients.example", source="test")
        unhappy = await resolve_contact(conn, oid, name="Rohit Sharma", email="rohit@patients.example", source="test")
    assert await rv.ask(oid, happy, "booking:1") == "no_link"  # nothing to send them to yet
    async with tenant_session(oid) as conn:
        await conn.execute(text("""update app.automation_instances set config = config || '{"review_link": "https://g.page/r/sample/review"}'"""))
    await rv.sync(oid)
    assert await rv.ask(oid, happy, "booking:1") == "recorded"  # no mailbox connected: recorded in the conversation
    assert await rv.ask(oid, happy, "booking:1") == "already"
    assert await rv.ask(oid, happy, "invoice:9") == "skipped"  # asked in the last 90 days
    assert await rv.ask(oid, unhappy, "booking:2") == "skipped"  # left a 2-star review
    async with tenant_session(oid) as conn:
        sent = (await conn.execute(text("""select m.body from app.messages m join app.conversations c on c.id = m.conversation_id
            where c.automation_key = 'reviews'"""))).scalars().all()
        notes = dict((await conn.execute(text("select reason, note from app.review_requests where status = 'skipped'"))).all())
    assert sent == [("Hi Neel, thank you for choosing Team Test Co! If you have a minute, a quick review really helps others find us: "
                    "https://g.page/r/sample/review")]
    assert notes == {"invoice:9": "asked in the last 90 days", "booking:2": "their last review was unhappy"}


async def test_monthly_report(team_org):
    oid, _h = await team_org(["reviews"])
    await rv.sync(oid)
    start = datetime.now(UTC).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    s = await rv.monthly(oid, start)
    assert s["title"] == f"Reviews for {start.strftime('%B %Y')}" and s["count"] >= 1 and "Replied to" in s["body"]


async def test_page_watcher_ignores_timestamps_and_explains_changes(team_org, monkeypatch):
    oid, _h = await team_org(["reviews"])
    async with tenant_session(oid) as conn:
        wid = (await conn.execute(text("""insert into app.watchers (org_id, kind, name, url) values (:o, 'page', 'Rival Dental offers',
            'https://rival-dental.example/offers') returning id::text"""), {"o": oid})).scalar_one()
    assert (await watchers.check(oid, wid))["first"] is True  # the starting point: nothing to report
    page = ["Rival Dental Studio\n\nTeeth cleaning and polishing: Rs 1,200\n\nUpdated 10:42"]

    async def fake_fetch(url):
        return "Rival Dental Studio", page[0]
    monkeypatch.setattr(watchers, "fetch", fake_fetch)
    await watchers.check(oid, wid)
    page[0] = page[0].replace("10:42", "11:05")
    assert (await watchers.check(oid, wid))["changed"] is False  # only the time changed
    page[0] = page[0].replace("Rs 1,200", "Rs 899 (Diwali offer)")
    r = await watchers.check(oid, wid)
    assert r["changed"] and r["summary"] == "Gone: Teeth cleaning and polishing: Rs 1,200; New: Teeth cleaning and polishing: Rs 899 (Diwali offer)"
    assert (await events(oid, "watch.changed"))[-1]["name"] == "Rival Dental offers"


async def test_price_watcher_threshold_stock_and_failures(team_org, monkeypatch):
    oid, _h = await team_org(["reviews"])
    async with tenant_session(oid) as conn:
        wid = (await conn.execute(text("""insert into app.watchers (org_id, kind, name, url, rule) values (:o, 'price', 'Sonicare at Shop',
            'https://shop.example/sonicare', '{"min_change_pct": 5}') returning id::text"""), {"o": oid})).scalar_one()
    await watchers.check(oid, wid)
    async with tenant_session(oid) as conn:
        assert (await conn.execute(text("select last_value->>'price' from app.watchers where id = cast(:i as uuid)"), {"i": wid})).scalar_one() == "3499.0"
    page = ["Philips Sonicare 3100\n\nPrice: ₹3,399\n\nIn stock."]

    async def fake_fetch(url):
        if page[0] is None:
            raise watchers.WatchError("the page answered 503")
        return "Philips Sonicare 3100", page[0]
    monkeypatch.setattr(watchers, "fetch", fake_fetch)
    assert (await watchers.check(oid, wid))["changed"] is False  # -2.9%: under the 5% rule
    page[0] = "Philips Sonicare 3100\n\nPrice: ₹2,999\n\nIn stock."
    r = await watchers.check(oid, wid)
    assert r["changed"] and r["summary"] == "Philips Sonicare 3100: price dropped from INR 3,399.00 to INR 2,999.00 (-11.8%)"
    page[0] = "Philips Sonicare 3100\n\nPrice: ₹2,999\n\nSold out."
    assert (await watchers.check(oid, wid))["summary"].endswith("out of stock")
    page[0] = None
    for _ in range(3):
        await watchers.check(oid, wid)
    async with tenant_session(oid) as conn:
        assert (await conn.execute(text("select status from app.watchers where id = cast(:i as uuid)"), {"i": wid})).scalar_one() == "error"
    assert [e["error"] for e in await events(oid, "watch.failing")] == ["the page answered 503"]


async def test_watch_api_roles_and_plan_limit(client, team_org):
    oid, h = await team_org(["competitor_watch"])
    got = {r: (await client.get("/org/watchers", headers=h[r])).status_code for r in ALL}
    expect(got, owner=200, manager=200, staff=200, finance=200, viewer=200, agentry=200)
    new = {"kind": "price", "name": "Sonicare at Shop", "url": "https://shop.example/sonicare"}
    assert (await client.post("/org/watchers", headers=h["staff"], json=new)).status_code == 403
    r = await client.post("/org/watchers", headers=h["owner"], json=new)
    assert r.status_code == 201 and r.json()["error"] is None
    wid = r.json()["id"]
    item = (await client.get("/org/watchers", headers=h["viewer"])).json()["items"][0]
    assert item["value"]["price"] == 3499.0 and item["rule"] == {"min_change_pct": 5.0} and item["every_minutes"] == 360
    assert (await client.post("/org/watchers", headers=h["owner"], json={**new, "url": "not a url"})).status_code == 422
    async with tenant_session(oid) as conn:
        await conn.execute(text("""update app.automation_instances set config = config || '{"max_pages": 1}'"""))
    assert (await client.post("/org/watchers", headers=h["owner"], json={**new, "name": "Another"})).status_code == 409
    assert (await client.put(f"/org/watchers/{wid}", headers=h["manager"], json={"status": "paused"})).status_code == 200
    assert (await client.delete(f"/org/watchers/{wid}", headers=h["manager"])).status_code == 200
    assert (await client.get("/org/watchers", headers=h["owner"])).json()["items"] == []

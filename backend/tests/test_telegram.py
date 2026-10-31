"""Telegram: a business's own bot for its customers, and Agentry's team bot (linking, Tools menu, cards with buttons,
alerts, content uploads), against a fake Telegram Bot API."""
import json
import uuid

import httpx
import pytest
from conftest import expect
from sqlalchemy import text
from test_invoice_e2e import go_live_invoice_client

from agentry import telegram_team
from agentry.automations.telegram_assistant import answer_telegram
from agentry.config import settings
from agentry.connectors import http
from agentry.db import system_session, tenant_session
from agentry.invoices import enroll_open
from agentry.worker import telegram_jobs
from agentry.worker.delivery import deliver_approved_reply, deliver_human_reply

TEAM = "111111:team-bot-token-abcdefghijklmnopqrstuvw"
SHOP = "222222:shop-bot-token-abcdefghijklmnopqrstuvw"
ALL = ("owner", "manager", "staff", "finance", "viewer", "agentry")


class FakeTelegram:
    def __init__(self):
        self.sent: list[dict] = []  # every sendMessage: {token, chat_id, text, buttons}
        self.queue: dict[str, list[dict]] = {}  # token -> updates waiting for getUpdates
        self.webhooks: dict[str, str | None] = {}
        self.files: dict[str, bytes] = {}
        self.blocked: set[int] = set()
        self.next_id = 100

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handle)

    def handle(self, req: httpx.Request) -> httpx.Response:
        url = str(req.url)
        if "/file/bot" in url:
            return httpx.Response(200, content=self.files[url.rsplit("/", 1)[-1]])
        token, method = url.split("/bot", 1)[1].split("/", 1)
        if token not in (TEAM, SHOP):
            return httpx.Response(401, json={"ok": False, "description": "Unauthorized"})
        body = json.loads(req.content or b"{}")
        ok = lambda result: httpx.Response(200, json={"ok": True, "result": result})
        if method == "getMe":
            return ok({"id": int(token.split(":")[0]), "is_bot": True, "username": "agentry_team_bot" if token == TEAM else "smilecraft_bot"})
        if method == "sendMessage":
            if body["chat_id"] in self.blocked:
                return httpx.Response(403, json={"ok": False, "description": "Forbidden: bot was blocked by the user"})
            self.next_id += 1
            self.sent.append({"token": token, "chat_id": body["chat_id"], "text": body["text"],
                              "buttons": [b for row in (body.get("reply_markup") or {}).get("inline_keyboard", []) for b in row]})
            return ok({"message_id": self.next_id})
        if method == "getUpdates":
            got, self.queue[token] = self.queue.get(token, []), []
            return ok(got)
        if method in ("setWebhook", "deleteWebhook"):
            self.webhooks[token] = body.get("url")
            return ok(True)
        if method == "answerCallbackQuery":
            return ok(True)
        if method == "getFile":
            return ok({"file_id": body["file_id"], "file_path": f"docs/{body['file_id']}"})
        return httpx.Response(404, json={"ok": False, "description": f"no fake for {method}"})

    def to(self, chat_id: int) -> list[dict]:
        return [m for m in self.sent if m["chat_id"] == chat_id]


_uid = iter(range(10_000_000, 99_999_999, 7919))


def message(chat_id: int, body: str = "", **extra) -> dict:
    return {"update_id": next(_uid), "message": {"message_id": next(_uid), "date": 1761800000, "chat": {"id": chat_id, "type": "private"},
                                                 "from": {"id": chat_id, "is_bot": False, "first_name": "Meera", "username": f"u{chat_id}"},
                                                 **({"text": body} if body else {}), **extra}}


def press(chat_id: int, data: str) -> dict:
    return {"update_id": next(_uid), "callback_query": {"id": str(next(_uid)), "data": data, "from": {"id": chat_id},
                                                        "message": {"message_id": 1, "chat": {"id": chat_id, "type": "private"}}}}


@pytest.fixture
def tg(monkeypatch):
    f = FakeTelegram()
    monkeypatch.setattr(http, "TRANSPORT", f.transport())
    monkeypatch.setattr(settings, "telegram_bot_token", TEAM)
    monkeypatch.setattr(settings, "telegram_mode", "polling")
    monkeypatch.setattr(telegram_team, "_username", None)
    return f


def chat() -> int:
    return 7_000_000_000 + uuid.uuid4().int % 1_000_000_000


async def link(client, h: dict, role: str, f: FakeTelegram) -> int:
    url = (await client.post("/org/telegram/link", headers=h[role])).json()["url"]
    assert url.startswith("https://t.me/agentry_team_bot?start=")
    c = chat()
    await telegram_team.handle_update(message(c, f"/start {url.split('start=')[1]}"))
    assert f.to(c)[-1]["text"].startswith("Connected:")
    return c


async def test_linking_tools_menu_and_notification_channel(client, team_org, tg):
    _oid, h = await team_org(["invoice_follow_up", "inbox_triage", "content_repurposing"])
    assert (await client.get("/org/telegram", headers=h["owner"])).json() == {"available": True, "bot": "agentry_team_bot", "linked": False,
                                                                              "username": None, "linked_at": None}
    owner = await link(client, h, "owner", tg)
    assert (await client.get("/org/telegram", headers=h["owner"])).json()["linked"] is True
    # a used code can't link anyone else
    url = (await client.post("/org/telegram/link", headers=h["manager"])).json()["url"]
    code = url.split("start=")[1]
    await telegram_team.handle_update(message(c1 := chat(), f"/start {code}"))
    await telegram_team.handle_update(message(c2 := chat(), f"/start {code}"))
    assert tg.to(c1)[-1]["text"].startswith("Connected:") and "expired" in tg.to(c2)[-1]["text"]
    # a stranger only gets instructions
    await telegram_team.handle_update(message(c3 := chat(), "hello"))
    assert "Connect Telegram" in tg.to(c3)[-1]["text"]
    # the Tools menu follows the business's agents and the person's role
    await telegram_team.handle_update(message(owner, "/tools"))
    menu = {b["callback_data"] for b in tg.to(owner)[-1]["buttons"]}
    assert menu == {"t:pulse", "t:needs", "t:inbox", "t:invoices", "t:leads", "t:content", "t:results"}
    finance = await link(client, h, "finance", tg)
    await telegram_team.handle_update(message(finance, "/tools"))
    assert {b["callback_data"] for b in tg.to(finance)[-1]["buttons"]} == {"t:pulse", "t:needs", "t:invoices", "t:results"}
    viewer = await link(client, h, "viewer", tg)
    await telegram_team.handle_update(message(viewer, "/tools"))
    assert {b["callback_data"] for b in tg.to(viewer)[-1]["buttons"]} == {"t:pulse", "t:invoices", "t:results"}
    for tool in ("needs", "inbox", "invoices", "leads", "content", "results"):  # every tool answers
        await telegram_team.handle_update(press(owner, f"t:{tool}"))
    replies = [m["text"] for m in tg.to(owner)[-6:]]
    assert replies[0].startswith("Nothing needs you") and replies[1].startswith("📥 Inbox") and replies[2].startswith("💰 Outstanding")
    assert replies[4].startswith("🎬 Content") and "Send me a video" in replies[4] and replies[5].startswith("📈")
    # Telegram becomes a notification channel once linked, and "cards" appear (Telegram only)
    prefs = (await client.get("/org/notifications", headers=h["owner"])).json()
    assert prefs["channels"] == ["email", "telegram"] and prefs["prefs"]["cards"] == ["telegram"]
    assert "cards" not in (await client.get("/org/notifications", headers=h["staff"])).json()["prefs"]  # not linked
    r = await client.put("/org/notifications", headers=h["owner"], json={"cards": ["email", "telegram"], "urgent": ["telegram"]})
    assert r.json()["prefs"]["cards"] == ["telegram"] and r.json()["prefs"]["urgent"] == ["telegram"]
    assert (await client.delete("/org/telegram", headers=h["owner"])).json() == {"linked": False}


async def test_cards_pushed_approved_edited_and_permissions(client, team_org, tg):
    oid, h = await go_live_invoice_client(client, team_org)  # invoices only, approval mode
    owner = await link(client, h, "owner", tg)
    finance = await link(client, h, "finance", tg)
    staff = await link(client, h, "staff", tg)
    async with tenant_session(oid) as conn:
        await enroll_open(conn, oid)
    from helpers import enrollment_for

    from agentry.sequences import send_step
    await send_step(oid, await enrollment_for(oid, "E-1"), 0)
    async with tenant_session(oid) as conn:
        aid = (await conn.execute(text("select id::text from app.approvals where kind = 'outbound_draft' order by created_at desc limit 1"))).scalar_one()
        assert (await conn.execute(text("select count(*) from app.events where type = 'approval.created' and payload->>'approval_id' = :a"),
                                   {"a": aid})).scalar_one() == 1  # the trigger announces every new card
    assert await telegram_jobs.push_card_step(oid, aid) == 2  # owner + finance can act on invoice cards; front desk can't
    card = tg.to(finance)[-1]
    assert card["text"].startswith("Message to send:") and {b["text"] for b in card["buttons"]} == {"✅ Approve & send", "✏️ Edit", "🗑 Discard"}
    assert not [m for m in tg.to(staff) if m["text"].startswith("Message to send")]
    await telegram_team.handle_update(press(staff, f"c:approve:{aid}"))
    assert "Couldn't do that: missing permission" in tg.to(staff)[-1]["text"]
    await telegram_team.handle_update(press(finance, f"c:approve:{aid}"))
    assert tg.to(finance)[-1]["text"].startswith("✅ Approved")
    await telegram_team.handle_update(press(owner, f"c:approve:{aid}"))
    assert "already approved" in tg.to(owner)[-1]["text"]
    async with tenant_session(oid) as conn:
        via = (await conn.execute(text("select metadata->>'via' from app.audit_log where target_id = :a and action like 'approval.%'"), {"a": aid})).scalar_one()
    assert via == "telegram"
    # edit: tap Edit, send the new text, it goes out as written
    await send_step(oid, await enrollment_for(oid, "E-2"), 0)
    async with tenant_session(oid) as conn:
        aid2 = (await conn.execute(text("select id::text from app.approvals where status = 'pending' order by created_at desc limit 1"))).scalar_one()
    await telegram_team.handle_update(press(owner, f"c:edit:{aid2}"))
    assert "Send me the new text" in tg.to(owner)[-1]["text"]
    await telegram_team.handle_update(message(owner, "Hi Rohan, a gentle reminder about invoice E-2. Thanks!"))
    assert tg.to(owner)[-1]["text"] == "✅ Sent with your changes."
    async with tenant_session(oid) as conn:
        st, body = (await conn.execute(text("select status, body from app.approvals where id = cast(:a as uuid)"), {"a": aid2})).one()
    assert st == "edited" and body.startswith("Hi Rohan, a gentle reminder")
    # someone who turned cards off doesn't get them; a card assigned to one person goes only to them
    await client.put("/org/notifications", headers=h["owner"], json={"cards": []})
    async with tenant_session(oid) as conn:
        aid3 = (await conn.execute(text("""insert into app.approvals (org_id, kind, automation_key, title, body) values (:o, 'escalation',
            'invoice_follow_up', 'Call Rohan about E-1', 'Reminders finished') returning id::text"""), {"o": oid})).scalar_one()
    assert await telegram_jobs.push_card_step(oid, aid3) == 1  # finance only
    await telegram_team.handle_update(press(finance, f"c:resolve:{aid3}"))
    assert tg.to(finance)[-1]["text"] == "✔️ Marked as handled."
    await telegram_team.handle_update(message(finance, "/needs"))
    assert tg.to(finance)[-1]["text"].startswith("Nothing needs you")


async def test_alerts_by_telegram_fall_back_to_email(client, team_org, tg, monkeypatch):
    from agentry.notify import alerts
    emails = []
    monkeypatch.setattr(alerts, "send_email", lambda to, s, b: emails.append(to.split("-")[0]))
    oid, h = await team_org(["inbox_triage"])
    owner = await link(client, h, "owner", tg)
    await client.put("/org/notifications", headers=h["owner"], json={"urgent": ["telegram"]})
    used = await alerts.send_owner_alert(oid, "URGENT email: Site down", "Client's site is down")
    assert used == "email+telegram" and tg.to(owner)[-1]["text"].startswith("🔔 URGENT email: Site down") and emails == ["manager"]
    tg.blocked.add(owner)  # they blocked the bot: email instead, nobody misses it
    emails.clear()
    assert await alerts.send_owner_alert(oid, "URGENT email: again", "x") == "email"
    assert sorted(emails) == ["manager", "owner"]


async def test_business_bot_answers_customers(client, team_org, tg, monkeypatch):
    oid, h = await team_org(["telegram_assistant"])
    got = {r: (await client.post("/org/connections/telegram", headers=h[r], json={"bot_token": SHOP})).status_code for r in ("staff", "finance", "viewer")}
    expect(got, staff=403, finance=403, viewer=403)
    bad = await client.post("/org/connections/telegram", headers=h["owner"], json={"bot_token": "999:not-a-real-token-abcdefghijklmnop"})
    assert bad.status_code == 422
    r = (await client.post("/org/connections/telegram", headers=h["owner"], json={"bot_token": SHOP})).json()
    assert r == {"connected": True, "username": "smilecraft_bot", "link": "https://t.me/smilecraft_bot", "delivery": "polling"}
    prof = (await client.get("/org/profile", headers=h["owner"])).json()
    assert {c["key"]: c["done"] for c in prof["go_live_checks"]}["telegram"] is True
    customer = chat()
    tg.queue[SHOP] = [message(customer, "/start"), message(customer, "Do you do teeth whitening? How much?")]
    assert await telegram_jobs.poll_once() == 2
    async with tenant_session(oid) as conn:
        conv, contact = (await conn.execute(text("select id::text, contact_id from app.conversations where channel = 'telegram'"))).one()
        evs = (await conn.execute(text("select payload from app.events where type = 'telegram.received' order by id"))).scalars().all()
        await conn.execute(text("update app.automation_instances set status = 'live' where template_key = 'telegram_assistant'"))
        tid = (await conn.execute(text("select attributes->>'telegram_id' from app.contacts where id = :c"), {"c": contact})).scalar_one()
    assert len(evs) == 2 and evs[0]["text"] == "Hi" and tid == str(customer)
    assert await telegram_jobs.poll_once() == 0  # nothing new: each update is handled once
    await answer_telegram({"org_id": oid, "payload": evs[1]})
    assert tg.to(customer) and tg.to(customer)[-1]["token"] == SHOP  # the assistant replied through the business's bot
    # approval mode: the reply waits; approving sends it through Telegram
    async with tenant_session(oid) as conn:
        await conn.execute(text("update app.automation_instances set status = 'approval_mode' where template_key = 'telegram_assistant'"))
    await answer_telegram({"org_id": oid, "payload": evs[1] | {"text": "And on Sundays?"}})
    card = next(a for a in (await client.get("/org/approvals", headers=h["owner"])).json()["items"] if a["kind"] == "reply_draft")
    assert card["title"] == "Telegram reply to Meera"
    before = len(tg.to(customer))
    dec = await client.post(f"/org/approvals/{card['id']}", headers=h["staff"], json={"action": "approve"})
    assert dec.status_code == 200, dec.text
    await deliver_approved_reply({"org_id": oid, "payload": {"approval_id": card["id"], "status": "approved", "kind": "reply_draft"}})
    assert len(tg.to(customer)) == before + 1
    # a person replies from the portal: it goes out on Telegram and the assistant steps back
    r = await client.post(f"/org/conversations/{conv}/reply", headers=h["staff"], json={"body": "Yes, 10 to 1 on Sundays."})
    await deliver_human_reply({"org_id": oid, "payload": {"message_id": r.json()["message_id"], "conversation_id": conv}})
    assert tg.to(customer)[-1]["text"] == "Yes, 10 to 1 on Sundays."
    # a voice note goes to the team with the busy reply
    tg.queue[SHOP] = [message(chat2 := chat(), voice={"file_id": "v1", "duration": 4})]
    await telegram_jobs.poll_once()
    async with tenant_session(oid) as conn:
        ev = (await conn.execute(text("select payload from app.events where type = 'telegram.received' order by id desc limit 1"))).scalar_one()
    await answer_telegram({"org_id": oid, "payload": ev})
    assert tg.to(chat2)[-1]["text"].startswith("Thanks for your message")
    assert any(a["title"].startswith("Telegram from Meera needs a person") for a in (await client.get("/org/approvals", headers=h["owner"])).json()["items"])


async def test_webhooks_check_their_secret(client, team_org, tg, monkeypatch):
    monkeypatch.setattr(settings, "telegram_webhook_secret", "s3cret")
    assert (await client.post("/webhooks/telegram/agentry", json=message(chat(), "hi"))).status_code == 403
    assert (await client.post("/webhooks/telegram/agentry", json=message(c := chat(), "hi"),
                              headers={"X-Telegram-Bot-Api-Secret-Token": "s3cret"})).status_code == 200
    assert "Connect Telegram" in tg.to(c)[-1]["text"]
    monkeypatch.setattr(settings, "telegram_mode", "webhook")
    _oid, h = await team_org(["telegram_assistant"])
    r = (await client.post("/org/connections/telegram", headers=h["owner"], json={"bot_token": SHOP})).json()
    assert r["delivery"] == "webhook" and tg.webhooks[SHOP].endswith("/webhooks/telegram/" + tg.webhooks[SHOP].rsplit("/", 1)[-1])
    cid = tg.webhooks[SHOP].rsplit("/", 1)[-1]
    async with system_session() as conn:
        secret = (await conn.execute(text("select state->>'webhook_secret' from app.connections where id::text = :i"), {"i": cid})).scalar_one()
    assert (await client.post(f"/webhooks/telegram/{cid}", json=message(chat(), "hi"))).status_code == 403
    ok = await client.post(f"/webhooks/telegram/{cid}", json=message(chat(), "Hello!"), headers={"X-Telegram-Bot-Api-Secret-Token": secret})
    assert ok.json() == {"stored": 1}


async def test_send_a_recording_to_the_bot(client, team_org, tg, monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "content_dir", str(tmp_path))
    oid, h = await team_org(["content_repurposing"])
    owner = await link(client, h, "owner", tg)
    staff = await link(client, h, "staff", tg)
    srt = b"1\n00:00:01,000 --> 00:00:09,000\nDr. Rao: Every patient gets a written plan with prices before we start.\n"
    tg.files["f1"] = srt
    doc = {"document": {"file_id": "f1", "file_name": "talk.srt", "file_size": len(srt)}, "caption": "Clinic talk"}
    await telegram_team.handle_update(message(staff, **doc))
    assert "only turn recordings into posts" in tg.to(staff)[-1]["text"]
    await telegram_team.handle_update(message(owner, **doc))
    assert tg.to(owner)[-1]["text"].startswith("Got it: “Clinic talk”")
    async with tenant_session(oid) as conn:
        s = (await conn.execute(text("select kind, title, transcript is not null as has_t from app.content_sources"))).mappings().one()
        ev = (await conn.execute(text("select count(*) from app.events where type = 'content.source_added'"))).scalar_one()
    assert dict(s) == {"kind": "transcript", "title": "Clinic talk", "has_t": True} and ev == 1
    big = {"video": {"file_id": "f2", "file_size": 50 * 1024 * 1024}}
    await telegram_team.handle_update(message(owner, **big))
    assert "up to 20 MB" in tg.to(owner)[-1]["text"]
    assert ALL

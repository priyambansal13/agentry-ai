"""AI receptionist / voice, every role: a receptionist client's portal, "Call back" cards from calls, deleting recordings,
recording retention, and call minutes on the statement (PHASE-4-VOICE.md 4.4, 4.6, 4.7)."""
import json
import uuid
from datetime import UTC, datetime
from decimal import Decimal

from conftest import expect
from sqlalchemy import text

from agentry import billing
from agentry.agents.tools import _handoff
from agentry.config import settings
from agentry.db import tenant_session
from agentry.voice.recordings import purge_expired
from agentry.voice.summary import create_callback, summarise

ALL = ("owner", "manager", "staff", "finance", "viewer", "agentry")


async def call(client, h, oid: str, lines: list[tuple[str, str]], *, seconds: int = 0, test: bool = True) -> str:
    """A finished call: test-call conversation + transcript, as the voice worker leaves it (closed, duration noted)."""
    cid = (await client.post("/org/voice/test-call", headers=h["owner"])).json()["conversation_id"]
    async with tenant_session(oid) as conn:
        for direction, body in lines:
            await conn.execute(text("""insert into app.messages (org_id, conversation_id, direction, author, body)
                values (:o, cast(:c as uuid), :d, :a, :b)"""), {"o": oid, "c": cid, "d": direction, "a": "contact" if direction == "in" else "agent", "b": body})
        await conn.execute(text("""update app.conversations set status = 'closed', metadata = metadata
            || jsonb_build_object('duration_seconds', cast(:s as int), 'test', cast(:t as boolean), 'ended_at', now()::text)
            where id = cast(:c as uuid)"""), {"c": cid, "s": seconds, "t": test})
    return cid


async def test_receptionist_client_portal(client, team_org):
    _oid, h = await team_org(["ai_receptionist"], live=False)
    f = (await client.get("/org/features", headers=h["owner"])).json()
    assert {"needs-you", "conversations", "knowledge"} <= set(f["pages"]) and "invoices" not in f["pages"]
    assert "test" in f["steps"]
    # can be tested in the browser now; going live waits for a phone number (milestone 4.3)
    prof = (await client.get("/org/profile", headers=h["owner"])).json()
    assert {c["key"]: c["done"] for c in prof["go_live_checks"]}["phone"] is False
    got = {r: (await client.post("/org/voice/test-call", headers=h[r])).status_code for r in ALL}
    expect(got, owner=201, manager=201, staff=403, finance=403, viewer=403, agentry=201)
    # receptionist settings follow the automation permissions
    got = {r: (await client.patch("/org/automations/ai_receptionist/config", headers=h[r], json={"answer_when": "always"})).status_code for r in ALL}
    expect(got, owner=200, manager=200, staff=403, finance=403, viewer=403, agentry=200)
    bad = await client.patch("/org/automations/ai_receptionist/config", headers=h["owner"], json={"transfer_number": "98765"})
    assert bad.status_code == 422


async def test_caller_asks_for_a_person_becomes_a_callback_card(client, team_org):
    oid, h = await team_org(["ai_receptionist"])
    cid = await call(client, h, oid, [("in", "Can I speak to the doctor about my bill?")], seconds=40)
    r = await _handoff(oid, cid, "wants to discuss a bill with the doctor", source="voice")
    assert "call them back" in r["tell_visitor"]
    async with tenant_session(oid) as conn:  # nobody can type into a call: no "Reply now" hand-off card
        assert (await conn.execute(text("select count(*) from app.approvals where conversation_id = cast(:c as uuid)"), {"c": cid})).scalar_one() == 0
        await conn.execute(text("update app.conversations set status = 'closed' where id = cast(:c as uuid)"), {"c": cid})  # call ends
    data = await summarise(oid, cid)
    assert data["outcome"] == "handed_off" and data["follow_up"] is True
    # the name and number the caller said (read from the transcript by the summary) become the contact to call back
    aid = await create_callback(oid, cid, data | {"caller_name": "Ravi Kumar", "callback_number": "+91 98765 43210"})
    assert aid and await create_callback(oid, cid, data) is None  # once per call
    conv = (await client.get(f"/org/conversations/{cid}", headers=h["staff"])).json()["conversation"]
    assert conv["contact_name"] == "Ravi Kumar"

    seen = {}
    for r in ALL:
        res = await client.get("/org/approvals", headers=h[r])
        seen[r] = res.status_code if res.status_code != 200 else 200 if any(
            i["id"] == aid and i["kind"] == "callback" for i in res.json()["items"]) else 404
    expect(seen, owner=200, manager=200, staff=200, finance=403, viewer=403, agentry=200)
    card = next(i for i in (await client.get("/org/approvals", headers=h["staff"])).json()["items"] if i["id"] == aid)
    assert card["title"].startswith("Test call: Call back Ravi Kumar") and card["payload"]["urgent"] is True
    assert card["payload"]["phone"] == "+919876543210"
    for r in ("finance", "viewer"):
        assert (await client.post(f"/org/approvals/{aid}", headers=h[r], json={"action": "resolve"})).status_code == 403
    assert (await client.post(f"/org/approvals/{aid}", headers=h["staff"], json={"action": "resolve"})).json()["status"] == "resolved"


async def test_a_plain_answered_call_needs_no_callback(client, team_org):
    oid, h = await team_org(["ai_receptionist"])
    cid = await call(client, h, oid, [("in", "What time do you open on Saturday?"), ("out", "We open at nine.")], seconds=20)
    data = await summarise(oid, cid)
    assert data["outcome"] == "answered" and not data["follow_up"]


async def test_delete_recording_and_retention(client, team_org, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "recordings_dir", str(tmp_path))
    oid, h = await team_org(["ai_receptionist"])

    async def recorded() -> str:
        cid = await call(client, h, oid, [("in", "Hello")], seconds=30)
        (tmp_path / oid).mkdir(exist_ok=True)
        (tmp_path / oid / f"{cid}.ogg").write_bytes(b"OggS" + b"\x00" * 2048)
        async with tenant_session(oid) as conn:
            await conn.execute(text("update app.conversations set metadata = metadata || jsonb_build_object('recording', cast(:r as text)) where id = cast(:c as uuid)"),
                               {"r": f"{oid}/{cid}.ogg", "c": cid})
        return cid

    cid = await recorded()
    got = {r: (await client.delete(f"/org/conversations/{cid}/recording", headers=h[r])).status_code for r in ("staff", "finance", "viewer")}
    expect(got, staff=403, finance=403, viewer=403)
    assert (await client.delete(f"/org/conversations/{cid}/recording", headers=h["manager"])).status_code == 200
    assert not (tmp_path / oid / f"{cid}.ogg").exists()
    assert (await client.delete(f"/org/conversations/{cid}/recording", headers=h["owner"])).status_code == 404
    conv = (await client.get(f"/org/conversations/{cid}", headers=h["owner"])).json()["conversation"]
    assert conv["metadata"]["recording_deleted"]["reason"] == "deleted on request"
    assert len((await client.get(f"/org/conversations/{cid}", headers=h["owner"])).json()["messages"]) >= 1  # transcript stays

    # retention: owner/manager choose how long; the daily job deletes older recordings
    got = {r: (await client.put("/org/voice/settings", headers=h[r], json={"recording_retention_days": 30})).status_code for r in ALL}
    expect(got, owner=200, manager=200, staff=403, finance=403, viewer=403, agentry=200)
    assert (await client.put("/org/voice/settings", headers=h["owner"], json={"recording_retention_days": 2})).status_code == 422
    assert (await client.get("/org/voice/settings", headers=h["owner"])).json()["recording_retention_days"] == 30
    old, new = await recorded(), await recorded()
    async with tenant_session(oid) as conn:
        await conn.execute(text("update app.conversations set created_at = now() - interval '31 days' where id = cast(:c as uuid)"), {"c": old})
    assert await purge_expired() >= 1
    assert not (tmp_path / oid / f"{old}.ogg").exists() and (tmp_path / oid / f"{new}.ogg").exists()
    conv = (await client.get(f"/org/conversations/{old}", headers=h["owner"])).json()["conversation"]
    assert conv["metadata"]["recording_deleted"]["reason"] == "retention" and "recording" not in conv["metadata"]


async def test_call_minutes_on_the_statement_and_margin(client, team_org):
    oid, h = await team_org(["ai_receptionist"])
    await call(client, h, oid, [("in", "Hi")], seconds=125, test=False)  # 3 billed minutes (rounded up)
    await call(client, h, oid, [("in", "Hi")], seconds=60, test=False)   # 1 minute
    await call(client, h, oid, [("in", "Hi")], seconds=600)              # test call: never billed
    async with tenant_session(oid) as conn:
        await billing.save_plan(conn, oid, billing.PricingPlan(retainer=Decimal(1000), included={"voice_minutes": 2},
                                                               overage={"voice_minutes": Decimal("4.50")}))
        sid = await billing.generate_statement(conn, oid, *billing.month_bounds(datetime.now(UTC).date()))
        line = (await conn.execute(text("select description, quantity, amount from app.statement_lines where statement_id = :s and kind = 'overage'"),
                                   {"s": sid})).one()
        assert line.quantity == 2 and line.amount == Decimal("9.00") and "Voice minutes" in line.description and "(4 used)" in line.description
        start = datetime.now(UTC).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        m = await billing.margin(conn, start, datetime.now(UTC))
    assert m["voice_minutes"] == round((125 + 60 + 600) / 60, 1)  # every call costs speech + telephony, test calls too


async def test_phone_number_assignment_and_inbound_call(client, team_org, monkeypatch):
    """HQ assigns one of Agentry's numbers; a call to it opens a conversation for that client, the caller becomes the
    contact, and the receptionist's go-live check passes. LiveKit's API is simulated."""
    from agentry.voice import telephony
    from agentry.voice.worker import start_phone_call
    # a valid US number (exchange codes never start with 0 or 1), different on every run
    number = f"+1484{200 + uuid.uuid4().int % 800}{uuid.uuid4().int % 10**4:04d}"
    calls: list[tuple] = []

    async def numbers():
        return [{"id": "PN_1", "number": number, "country": "US", "locality": "READING", "status": "offline", "dispatch_rule_id": None}]

    async def twirp(method, body):
        calls.append((method, body))
        return {}

    async def ensure_rule(lk, n):
        return f"SDR_{n}"
    monkeypatch.setattr(telephony, "project_numbers", numbers)
    monkeypatch.setattr(telephony, "_twirp", twirp)
    monkeypatch.setattr(telephony, "_ensure_rule", ensure_rule)

    oid, h = await team_org(["ai_receptionist"])
    other, _h2 = await team_org(["website_chat"])
    staff = h["agentry"]
    # only Agentry staff assign numbers, and only to a client with the receptionist
    assert (await client.put(f"/hq/orgs/{oid}/phone", headers=h["owner"], json={"number": number})).status_code == 403
    assert (await client.put(f"/hq/orgs/{other}/phone", headers=staff, json={"number": number})).status_code == 409
    assert (await client.put(f"/hq/orgs/{oid}/phone", headers=staff, json={"number": "+14155550000"})).status_code == 409
    r = await client.put(f"/hq/orgs/{oid}/phone", headers=staff, json={"number": number})
    assert r.status_code == 200 and calls[-1] == ("UpdatePhoneNumber", {"id": "PN_1", "sip_dispatch_rule_ids": [f"SDR_{number}"]})
    listed = (await client.get("/hq/phone-numbers", headers=staff)).json()["items"]
    assert listed[0]["client"]["org_id"] == oid
    prof = (await client.get("/org/profile", headers=h["owner"])).json()
    assert {c["key"]: c["done"] for c in prof["go_live_checks"]}["phone"] is True

    # a call comes in: the client is found from the dialled number, the caller becomes the contact
    org_id, cid = await start_phone_call(number, "+919876543210")
    assert org_id == oid
    conv = (await client.get(f"/org/conversations/{cid}", headers=h["staff"])).json()
    assert conv["conversation"]["channel"] == "voice" and conv["conversation"]["contact_phone"] in ("+919876543210", "+91 98765 43210")
    assert "AI assistant" in conv["messages"][0]["body"] and conv["conversation"]["metadata"]["inbound"] is True
    # unknown numbers and a paused receptionist don't answer
    assert await start_phone_call("+14155550000", "+919876543210") is None
    assert (await client.post("/org/automations/ai_receptionist/pause", headers=h["owner"])).status_code == 200
    assert await start_phone_call(number, "+919876543210") is None
    # unassigning stops it for this client
    assert (await client.delete(f"/hq/orgs/{oid}/phone/{number}", headers=staff)).status_code == 200
    assert await start_phone_call(number, "+919876543210") is None


async def test_call_is_evidence_on_the_statement(client, team_org, tmp_path, monkeypatch):
    """A booking made on a call: the statement shows the call (length, summary) and finance may play it."""
    monkeypatch.setattr(settings, "recordings_dir", str(tmp_path))
    oid, h = await team_org(["ai_receptionist"])
    cid = await call(client, h, oid, [("in", "Book me a cleaning on Monday")], seconds=95, test=False)
    (tmp_path / oid).mkdir()
    (tmp_path / oid / f"{cid}.ogg").write_bytes(b"OggS" + b"\x00" * 2048)
    async with tenant_session(oid) as conn:
        await conn.execute(text("""update app.conversations set metadata = metadata || jsonb_build_object('recording', cast(:r as text),
            'call', jsonb_build_object('summary', 'Booked a cleaning for Monday.')) where id = cast(:c as uuid)"""), {"r": f"{oid}/{cid}.ogg", "c": cid})
    # before it is evidence on a statement, finance can't hear the call
    assert (await client.get(f"/org/conversations/{cid}/recording", headers=h["finance"])).status_code == 403
    async with tenant_session(oid) as conn:
        await conn.execute(text("""insert into app.outcomes (org_id, kind, source_ref, occurred_at, value, automation_key, evidence)
            values (:o, 'appointment_booked', :r, now(), 1500, 'ai_receptionist', cast(:e as jsonb))"""),
            {"o": oid, "r": str(uuid.uuid4()), "e": json.dumps({"service": "Cleaning", "source": "voice", "conversation_id": cid})})
        await billing.save_plan(conn, oid, billing.PricingPlan(outcome_prices=[{"outcome": "appointment_booked", "price": 300}]))
        sid = await billing.generate_statement(conn, oid, *billing.month_bounds(datetime.now(UTC).date()))
        await billing.issue(conn, oid, sid)
    st = (await client.get(f"/org/billing/statements/{sid}", headers=h["finance"])).json()
    evidence = next(o for o in st["evidence"].values() if o["evidence"].get("source") == "voice")
    assert evidence["call"] == {"conversation_id": cid, "duration_seconds": 95, "summary": "Booked a cleaning for Monday.", "recording": True}
    got = {r: (await client.get(f"/org/conversations/{cid}/recording", headers=h[r])).status_code for r in ALL}
    expect(got, owner=200, manager=200, staff=200, finance=200, viewer=403, agentry=200)


async def test_ops_alerts_for_calls(client, team_org):
    from agentry import ops
    oid, h = await team_org(["ai_receptionist"])
    stuck = await call(client, h, oid, [("in", "Hello?")])
    slow = await call(client, h, oid, [("in", "Hi")], seconds=30)
    async with tenant_session(oid) as conn:
        await conn.execute(text("""update app.conversations set created_at = now() - interval '35 minutes', metadata = metadata - 'ended_at'
            where id = cast(:c as uuid)"""), {"c": stuck})
        await conn.execute(text("""update app.conversations set metadata = metadata || jsonb_build_object('ended_at', now()::text,
            'turns', 3, 'failed_turns', 1, 'latency_ms', jsonb_build_object('avg', 5200, 'max', 7000)) where id = cast(:c as uuid)"""), {"c": slow})
    problems = "\n".join(await ops.check(minutes=10))
    assert "never finished" in problems and "Team Test Co" in problems
    assert f"/conversations/{slow}" in problems and "couldn't answer 1 of 3" in problems
    assert "slow: average reply 5.2 s" in problems

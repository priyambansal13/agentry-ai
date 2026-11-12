"""Missed-call recovery (automations/missed_call): the phone system's webhook (common providers' fields), who gets a
WhatsApp and who doesn't, consent, once a day, and replies / bookings counted against the missed call."""
from sqlalchemy import text

from agentry.automations import missed_call as mc
from agentry.db import tenant_session


async def _org(client, team_org, monkeypatch, informed: bool = True):
    oid, h = await team_org(["missed_call_recovery", "whatsapp_assistant"])
    async with tenant_session(oid) as conn:
        await conn.execute(text("""update app.automation_instances set config = config || cast(:c as jsonb) where template_key = 'missed_call_recovery'"""),
                           {"c": f'{{"callers_informed": {str(informed).lower()}, "whatsapp_template": "missed_call_hello", "skip_numbers": ["+91 98100 99999"]}}'})
    sent = []

    async def fake_reach(conn, org_id, who, body, **kw):
        sent.append((who["phone_e164"], body, kw.get("wa_template"), kw.get("wa_params")))
        return {"status": "sent", "channel": "whatsapp", "conversation_id": None}
    monkeypatch.setattr("agentry.outbound.reach_contact", fake_reach)
    page = (await client.get("/org/missed-calls", headers=h["owner"])).json()
    return oid, h, page["hook_url"].rsplit("/", 1)[1], sent


def test_statuses_from_different_phone_systems():
    assert mc.is_missed({"DialCallStatus": "no-answer"}) and mc.is_missed({"call_status": "Missed"}) and mc.is_missed({"Status": "busy"})
    assert mc.is_missed({"status": "NOT ANSWERED"}) and mc.is_missed({"missed": "true"})
    assert not mc.is_missed({"Status": "completed"}) and not mc.is_missed({"CallStatus": "answered"}) and not mc.is_missed({})
    assert mc.pick({"CallFrom": "09810000011"}, mc.FROM) == "09810000011"


async def test_a_missed_call_gets_one_whatsapp(client, team_org, monkeypatch):
    oid, h, key, sent = await _org(client, team_org, monkeypatch)
    # Exotel-style form post; an answered call is ignored
    assert (await client.post(f"/hooks/calls/{key}", data={"CallFrom": "09810000011", "DialCallStatus": "completed"})).json()["recorded"] is False
    r = (await client.post(f"/hooks/calls/{key}", data={"CallFrom": "09810000011", "CallTo": "08040001234", "DialCallStatus": "no-answer"})).json()
    assert r["recorded"]
    assert (await client.post("/hooks/calls/mc_nope", json={"From": "+919810000011", "Status": "missed"})).status_code == 404
    assert await mc.missed_call_send_step(oid, r["id"]) == "sent"
    assert sent[0][0] == "+919810000011" and sent[0][2] == "missed_call_hello" and sent[0][3] == ["Team Test Co"]
    assert "Team Test Co" in sent[0][1]
    async with tenant_session(oid) as conn:
        consent = (await conn.execute(text("select status, source from app.consents where channel = 'whatsapp'"))).one()
    assert tuple(consent) == ("granted", "missed_call")
    # the same caller again today: no second message (GET with query parameters works too)
    r2 = (await client.get(f"/hooks/calls/{key}?caller=%2B919810000011&status=missed")).json()
    assert await mc.missed_call_send_step(oid, r2["id"]) == "already messaged today"
    # a staff number is never messaged
    r3 = (await client.post(f"/hooks/calls/{key}", json={"from": "+919810099999", "status": "missed"})).json()
    assert await mc.missed_call_send_step(oid, r3["id"]) == "one of your own numbers"
    assert len(sent) == 1

    # they book within the week: the missed call counts as recovered
    async with tenant_session(oid) as conn:
        contact = (await conn.execute(text("select contact_id::text from app.missed_calls where id = cast(:i as uuid)"), {"i": r["id"]})).scalar_one()
    await mc.missed_booking_step(oid, contact, "00000000-0000-0000-0000-000000000001")
    page = (await client.get("/org/missed-calls", headers=h["viewer"])).json()
    assert page["stats"]["30"] == {"missed": 3, "messaged": 1, "replied": 0, "booked": 1}
    assert next(c for c in page["calls"] if c["id"] == r["id"])["booked_at"]


async def test_nothing_goes_until_callers_are_told(client, team_org, monkeypatch):
    oid, _h, key, sent = await _org(client, team_org, monkeypatch, informed=False)
    r = (await client.post(f"/hooks/calls/{key}", json={"From": "+919810000022", "Status": "no-answer"})).json()
    assert (await mc.missed_call_send_step(oid, r["id"])).startswith("callers aren't told") and not sent


async def test_opted_out_callers_are_left_alone(client, team_org, monkeypatch):
    from agentry.leads import opt_out
    oid, _h, key, sent = await _org(client, team_org, monkeypatch)
    r = (await client.post(f"/hooks/calls/{key}", json={"From": "+919810000033", "Status": "no-answer"})).json()
    async with tenant_session(oid) as conn:
        cid = (await conn.execute(text("select contact_id::text from app.missed_calls where id = cast(:i as uuid)"), {"i": r["id"]})).scalar_one()
        await opt_out(conn, oid, cid, "whatsapp", "test")
    assert await mc.missed_call_send_step(oid, r["id"]) == "opted out of WhatsApp" and not sent


async def test_test_call_and_roles(client, team_org, monkeypatch):
    _oid, h, _key, _sent = await _org(client, team_org, monkeypatch)
    assert (await client.post("/org/missed-calls/test", headers=h["owner"], json={"phone": "+919810000044"})).json()["recorded"]
    assert (await client.post("/org/missed-calls/test", headers=h["viewer"], json={"phone": "+919810000044"})).status_code == 403
    _oid2, h2 = await team_org(["inbox_triage"])
    assert (await client.get("/org/missed-calls", headers=h2["owner"])).status_code == 404

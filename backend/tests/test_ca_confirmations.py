"""Balance confirmations (docs/PLAN-CA-DESK-2.md #7): the sample balances (Mehta Steel, 31 Mar 2026) read and selected,
nothing sent until Send is pressed (and test addresses never emailed), the party's private link (agree / their figure /
statement filed), a pasted email reply read by rules, the AI only when they can't tell and never with a figure that isn't
in the reply, staff setting a result and adding an email, reminders, the summary and Excel, the website box."""
import io
import json
import re
from types import SimpleNamespace

from openpyxl import load_workbook
from sqlalchemy import text

from agentry.automations.ca import confirmations as cf
from agentry.automations.ca.taxdocs import SAMPLES
from agentry.db import tenant_session


def test_read_and_rules():
    rows = [r.split(",") for r in ["Party,Debit,Credit,Email", "A Ltd,1000,,a@x.example", "B Ltd,,500,", "C Ltd,0,0,c@x.example"]]
    parties, used = cf.read(rows)
    assert [(p["party"], p["kind"], p["balance"], p["email"]) for p in parties] == [("A Ltd", "debtor", 1000, "a@x.example"), ("B Ltd", "creditor", -500, None)]
    assert used["debit"] == "Debit"
    assert cf.read_rules("We confirm the balance of Rs 1,20,000.", 120000)["status"] == "agreed"
    assert cf.read_rules("We confirm 1,10,000", 120000) is None  # agrees but with another figure: not taken as agreed
    assert cf.read_rules("Not matching. As per our books the balance is Rs 1,05,500; your invoice 2,000 of 30.03.2026 is in transit", 120000) == \
        {"status": "differs", "their_balance": 105500}
    assert cf.read_rules("We don't agree: nothing is due, fully paid", 120000) == {"status": "differs", "their_balance": 0.0}
    assert cf.read_rules("I'm on leave till Monday", 120000) is None
    assert cf.inr(1234567.5) == "₹12,34,567.50"


async def test_ai_only_for_unclear_and_never_invents(monkeypatch):
    calls = []

    async def fake(tier, msgs, **kw):
        calls.append(msgs[-1]["content"])
        return SimpleNamespace(data={"status": "differs", "their_balance": 99999, "why": "guess"})
    monkeypatch.setattr(cf, "complete", fake)
    p = {"party": "A", "kind": "debtor", "our_balance": 120000.0, "client": "Mehta"}
    assert (await cf.read_reply("org", "We confirm the balance.", p))["read_by"] == "rules" and not calls
    got = await cf.read_reply("org", "Please check with Mr. Rao, he says around 1,18,000 maybe", p)
    assert calls and got["status"] == "unclear" and got["their_balance"] is None  # 99,999 isn't in the reply


async def test_flow(client, team_org):
    oid, h = await team_org(["ca_filing_tracker"])
    cid = (await client.post("/org/ca/clients", headers=h["owner"], json={"name": "Mehta Steel Pvt Ltd", "kind": "company"})).json()["id"]
    assert (await client.post(f"/org/ca/clients/{cid}/confirmations/sample", headers=h["viewer"])).status_code == 403
    s = await client.post(f"/org/ca/clients/{cid}/confirmations/sample", headers=h["owner"])
    assert s.status_code == 201, s.text
    wid, r = s.json()["id"], s.json()["result"]
    st = {p["party"]: p["status"] for p in r["parties"]}
    assert st["Shah Engineering Works"] == "draft" and st["Sunrise Steels"] == "no_email" and st["Walk-in customers"] == "not_selected"
    assert r["summary"]["debtor"]["drafts"] == 5 and r["summary"]["creditor"]["drafts"] == 5

    sent = await client.post(f"/org/ca/work/{wid}/confirmations/send", headers=h["owner"], json={})
    assert sent.status_code == 200, sent.text
    assert sent.json()["sent"] == 10 and all(m["via"] == "recorded" for m in sent.json()["messages"])  # .example / example.com: never emailed
    body = next(m["body"] for m in sent.json()["messages"] if "₹4,85,600.00 receivable from you" in m["body"])
    token = re.search(r"/confirm/(\S+)", body)[1]

    v = await client.get(f"/public/confirm/{token}")
    assert v.status_code == 200 and v.json()["party"] == "Shah Engineering Works" and v.json()["balance"] == 485600
    a = await client.post(f"/public/confirm/{token}", data={"agree": "false", "their_balance": "460600", "note": "our payment of 25,000 on 30 Mar"},
                          files={"file": ("ledger.csv", b"Date,Amount\n30/03/2026,25000\n", "text/csv")})
    assert a.status_code == 200, a.text
    assert a.json()["status"] == "differs"
    assert (await client.get("/public/confirm/not-a-token")).status_code == 404

    w = (await client.get(f"/org/ca/work/{wid}", headers=h["owner"])).json()["result"]
    pid = {p["party"]: p["id"] for p in w["parties"]}
    shah = next(p for p in w["parties"] if p["party"] == "Shah Engineering Works")
    assert shah["difference"] == 25000 and shah["reply_via"] == "link" and shah["reply_file_id"]
    rep = await client.post(f"/org/ca/work/{wid}/confirmations/{pid['Tata Steel Ltd']}/reply", headers=h["owner"],
                            json={"text": json.loads((SAMPLES / "confirmation_replies_sample.json").read_text())["Tata Steel Ltd"]})
    assert rep.json()["status"] == "differs" and rep.json()["their_balance"] == 564300
    ok = await client.post(f"/org/ca/work/{wid}/confirmations/{pid['JSW Steel Ltd']}", headers=h["owner"], json={"status": "agreed", "note": "letter"})
    assert ok.status_code == 200 and ok.json()["summary"]["creditor"]["agreed"] == 1
    assert (await client.post(f"/org/ca/work/{wid}/confirmations/{pid['Bharat Bearings']}", headers=h["owner"], json={"status": "differs"})).status_code == 422
    em = await client.post(f"/org/ca/work/{wid}/confirmations/{pid['Sunrise Steels']}", headers=h["owner"], json={"email": "ap@sunrise.example"})
    assert em.json()["summary"]["debtor"]["drafts"] == 1

    async with tenant_session(oid) as conn:  # a week passes with no reply
        await conn.execute(text("update app.ca_confirmations set last_sent_at = now() - interval '8 days' where status = 'sent'"))
    rem = (await client.post(f"/org/ca/work/{wid}/confirmations/send", headers=h["owner"], json={"reminder": True})).json()
    assert rem["sent"] == 7 and rem["messages"][0]["subject"].startswith("Reminder:")
    assert (await client.get(f"/public/confirm/{token}")).status_code == 200  # earlier links still work
    x = await client.get(f"/org/ca/work/{wid}/sheet.xlsx", headers=h["owner"])
    assert x.status_code == 200
    wb = load_workbook(io.BytesIO(x.content))
    assert wb.sheetnames == ["Summary", "Parties", "To reconcile"] and wb["To reconcile"].max_row == 3


async def test_website_box(client):
    s = (await client.get("/public/playground/confirmations/sample")).json()
    r = await client.post("/public/playground/confirmations", headers={"x-forwarded-for": "203.0.113.83"}, json={"input": s})
    assert r.status_code == 200, r.text
    st = {p["party"]: (p["status"], p.get("their_balance")) for p in r.json()["parties"]}
    assert st["Kaveri Industries"] == ("differs", 287400) and st["Tata Steel Ltd"] == ("differs", 564300) and st["Delta Pumps Pvt Ltd"][0] == "unclear"
    src = (await client.get("/public/sources/ca-balance-confirmations")).json()
    assert "auditor" in src["basis"] and any("SA 505" in str(x) for x in src.values())

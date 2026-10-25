"""Invoice follow-up, end to end, for every role. Invoice items are money: they follow the invoice permission.

                                       owner manager front-desk finance viewer agentry
invoices: see                            ✓     ✓        –          ✓      ✓      ✓
import, record payment, pause reminders  ✓     ✓        –          ✓      –      ✓
reminder drafts, disputes in Needs you   ✓     ✓        –          ✓      –(see) ✓
invoice conversations (see / reply)      ✓     ✓        –          ✓      see    ✓
other conversations (e.g. website chat)  ✓     ✓        ✓          –      –      ✓
connect Razorpay / Stripe                ✓     ✓        –          –      –      ✓
"""
from datetime import UTC, datetime, timedelta

from conftest import expect
from helpers import csv_bytes, enrollment_for, import_invoices, inv
from sqlalchemy import text

from agentry.automations.invoice_follow_up import act_on_reply
from agentry.db import tenant_session
from agentry.sequences import send_step

ALL = ("owner", "manager", "staff", "finance", "viewer", "agentry")
INVOICE_READ = {"owner": 200, "manager": 200, "staff": 403, "finance": 200, "viewer": 200, "agentry": 200}
INVOICE_ACT = {"owner": 200, "manager": 200, "staff": 403, "finance": 200, "viewer": 403, "agentry": 200}


async def statuses(client, h, method, path, roles=ALL, **kw):
    return {r: (await client.request(method, path, headers=h[r], **kw)).status_code for r in roles}


async def test_invoice_follow_up_every_role(client, team_org):
    oid, h = await team_org(["invoice_follow_up", "website_chat"])
    async with tenant_session(oid) as conn:
        await conn.execute(text("update app.automation_instances set status = 'approval_mode' where template_key = 'invoice_follow_up'"))
    today = datetime.now(UTC).date()

    # import: only people who act on invoices
    rows = [inv(f"R-{r}", today - timedelta(days=15), email=f"{r}@payer.example") for r in ALL]
    files = {"file": ("inv.csv", csv_bytes(rows), "text/csv")}
    got = {r: (await client.post("/org/invoices/import", headers=h[r], files=files, data={"preview": "true"})).status_code for r in ALL}
    expect(got, **INVOICE_ACT)
    await import_invoices(oid, rows)
    expect(await statuses(client, h, "GET", "/org/invoices"), **INVOICE_READ)

    # a reminder per invoice is drafted (approval mode); each role tries to approve "its" reminder
    for r in ALL:
        await send_step(oid, await enrollment_for(oid, f"R-{r}"), 1)
    seen = {r: await client.get("/org/approvals", headers=h[r]) for r in ALL}
    expect({r: x.status_code for r, x in seen.items()}, owner=200, manager=200, staff=200, finance=200, viewer=200, agentry=200)
    kinds = {r: {a["automation_key"] for a in x.json()["items"]} for r, x in seen.items()}
    assert kinds["staff"] == set()  # the front desk sees no invoice items
    assert kinds["finance"] == {"invoice_follow_up"} and kinds["viewer"] == {"invoice_follow_up"}
    drafts = {a["title"]: a["id"] for a in seen["owner"].json()["items"] if a["kind"] == "outbound_draft"}
    got = {r: (await client.post(f"/org/approvals/{next(v for k, v in drafts.items() if f'R-{r}' in k)}", headers=h[r],
                                 json={"action": "reject"})).status_code for r in ALL}
    expect(got, **INVOICE_ACT)

    # a customer disputes an invoice: the dispute card follows the invoice permission too
    async with tenant_session(oid) as conn:
        r_ = (await conn.execute(text("select id, number, contact_id from app.invoices where number = 'R-finance'"))).one()
    assert await act_on_reply(oid, {"id": str(r_.id), "number": r_.number, "contact_id": str(r_.contact_id)}, None,
                              "this amount is wrong", {"label": "dispute", "reason": "billed twice"}, 1) == "dispute"
    dispute = next(a for a in (await client.get("/org/approvals", headers=h["finance"])).json()["items"] if a["kind"] == "dispute")
    expect({r: (await client.post(f"/org/approvals/{dispute['id']}", headers=h[r], json={"action": "resolve"})).status_code
            for r in ("staff", "viewer")}, staff=403, viewer=403)
    assert (await client.post(f"/org/approvals/{dispute['id']}", headers=h["finance"], json={"action": "resolve"})).status_code == 200

    # invoice actions
    async with tenant_session(oid) as conn:
        ids = {n: str(i) for n, i in (await conn.execute(text("select number, id from app.invoices"))).all()}
    got = {r: (await client.post(f"/org/invoices/{ids[f'R-{r}']}/payments", headers=h[r],
                                 json={"amount": 45000, "reference": f"UTR-{r}"})).status_code for r in ALL}
    expect(got, **{r: (201 if c == 200 else c) for r, c in INVOICE_ACT.items()})
    expect(await statuses(client, h, "POST", f"/org/invoices/{ids['R-viewer']}/reminders/pause"), **INVOICE_ACT)

    # conversations: finance sees invoice conversations only; the front desk sees everything but invoices
    async with tenant_session(oid) as conn:
        inv_conv = str((await conn.execute(text("""insert into app.conversations (org_id, channel, automation_key, subject, external_ref)
            values (:o, 'email', 'invoice_follow_up', 'Invoice R-owner', 'test-inv-1') returning id"""), {"o": oid})).scalar_one())
        chat_conv = str((await conn.execute(text("""insert into app.conversations (org_id, channel, automation_key, subject, external_ref)
            values (:o, 'web_chat', 'website_chat', 'Website chat', 'test-chat-1') returning id"""), {"o": oid})).scalar_one())
    lists = {r: await client.get("/org/conversations", headers=h[r]) for r in ALL}
    ids_by = {r: {c["id"] for c in x.json()["items"]} if x.status_code == 200 else None for r, x in lists.items()}
    assert ids_by["finance"] == {inv_conv} and ids_by["viewer"] == {inv_conv}
    assert inv_conv not in ids_by["staff"] and chat_conv in ids_by["staff"]
    assert {inv_conv, chat_conv} <= ids_by["owner"]
    expect(await statuses(client, h, "GET", f"/org/conversations/{inv_conv}"), **INVOICE_READ)
    expect(await statuses(client, h, "GET", f"/org/conversations/{chat_conv}"),
           owner=200, manager=200, staff=200, finance=403, viewer=403, agentry=200)
    expect(await statuses(client, h, "POST", f"/org/conversations/{chat_conv}/reply", json={"body": "hi"}),
           owner=201, manager=201, staff=201, finance=403, viewer=403, agentry=201)
    expect(await statuses(client, h, "POST", f"/org/conversations/{inv_conv}/status", json={"status": "closed"}), **INVOICE_ACT)

    # payment gateways: connection managers only
    expect(await statuses(client, h, "POST", "/org/connections/razorpay", roles=("staff", "finance", "viewer"),
                          json={"key_id": "rzp_test_x", "key_secret": "x" * 20, "webhook_secret": "y" * 20}),
           staff=403, finance=403, viewer=403)

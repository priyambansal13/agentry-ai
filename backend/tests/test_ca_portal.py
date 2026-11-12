"""CA client portal (automations/ca/portal.py): the firm's settings, a private link per client, what the client sees,
a document sent through it landing on the checklist, revoking, and the usage line on the firm's statement."""
from datetime import UTC, date, datetime

from sqlalchemy import text

from agentry import billing
from agentry.db import tenant_session

CA = ["ca_filing_tracker", "ca_document_chaser", "ca_compliance_calendar"]
RAMESH = {"name": "Ramesh Gupta", "pan": "ABCPG1234K", "phone": "+91 98100 00055", "email": "ramesh@example.com", "profile": {"salaried": True, "gst": True}}


async def _setup(client, team_org):
    oid, h = await team_org(CA)
    cid = (await client.post("/org/ca/clients", headers=h["owner"], json=RAMESH)).json()["id"]
    await client.post("/org/ca/filings", headers=h["owner"], json={"client_id": cid, "kind": "itr", "period": "AY 2026-27", "due_on": "2026-12-31"})
    return oid, h, cid


async def test_portal_link_view_upload_and_revoke(client, team_org):
    oid, h, cid = await _setup(client, team_org)
    assert (await client.post(f"/org/ca/clients/{cid}/portal", headers=h["owner"])).status_code == 409  # not switched on yet
    assert (await client.put("/org/ca/portal", headers=h["staff"], json={"enabled": True})).status_code == 403  # front desk can't
    s = (await client.put("/org/ca/portal", headers=h["owner"], json={"enabled": True, "title": "Sharma & Associates", "color": "#0b5d4b"})).json()
    assert s["enabled"] and s["title"] == "Sharma & Associates"
    assert (await client.put("/org/ca/portal", headers=h["owner"], json={"enabled": True, "logo_url": "http://x.example/l.png"})).status_code == 422

    link = (await client.post(f"/org/ca/clients/{cid}/portal", headers=h["staff"])).json()  # front desk shares links
    token = link["url"].rsplit("/", 1)[1]
    v = (await client.get(f"/public/portal/{token}")).json()
    assert v["firm"]["title"] == "Sharma & Associates" and v["firm"]["color"] == "#0b5d4b" and v["client"]["name"] == "Ramesh Gupta"
    itr = next(f for f in v["filings"] if f["title"] == "ITR AY 2026-27")
    assert {"form16", "bank_statements"} <= {n["key"] for n in itr["needed"]}
    assert v["due"] and all("source" in d for d in v["due"])  # GST dates, each with where it comes from

    stmt = b"Date,Narration,Withdrawal Amt.,Deposit Amt.,Closing Balance\n01/04/25,SALARY,,150000,150000\n"
    r = await client.post(f"/public/portal/{token}/files", files={"file": ("hdfc bank statement.csv", stmt, "text/csv")}, data={"filing_id": itr["id"]})
    assert r.status_code == 201, r.text
    after = (await client.get(f"/public/portal/{token}")).json()
    assert "bank_statements" not in {n["key"] for n in next(f for f in after["filings"] if f["id"] == itr["id"])["needed"]}
    assert after["files"][0]["filename"] == "hdfc bank statement.csv"
    async with tenant_session(oid) as conn:
        src = (await conn.execute(text("select source from app.ca_files"))).scalar_one()
        used = (await conn.execute(text("select count(*) from app.events where type = 'ca.portal_used'"))).scalar_one()
    assert src == "client_portal" and used == 1  # counted once a month, however often they open it
    st = (await client.get(f"/org/ca/clients/{cid}/portal", headers=h["owner"])).json()["link"]
    assert st["uses"] >= 3

    # a new link replaces the old one; revoking ends it
    new = (await client.post(f"/org/ca/clients/{cid}/portal", headers=h["owner"])).json()["url"].rsplit("/", 1)[1]
    assert (await client.get(f"/public/portal/{token}")).status_code == 404
    await client.delete(f"/org/ca/clients/{cid}/portal", headers=h["owner"])
    assert (await client.get(f"/public/portal/{new}")).status_code == 404
    assert (await client.get("/public/portal/not-a-token")).status_code == 404


async def test_portal_clients_on_the_statement(client, team_org):
    oid, h, cid = await _setup(client, team_org)
    await client.put("/org/ca/portal", headers=h["owner"], json={"enabled": True})
    token = (await client.post(f"/org/ca/clients/{cid}/portal", headers=h["owner"])).json()["url"].rsplit("/", 1)[1]
    await client.get(f"/public/portal/{token}")
    today = datetime.now(UTC).date()
    async with tenant_session(oid) as conn:
        await billing.save_plan(conn, oid, billing.PricingPlan(retainer=14999, overage={"portal_clients": 99}))
        sid = await billing.generate_statement(conn, oid, date(today.year, today.month, 1), today)
        lines = (await conn.execute(text("select description, quantity, unit_price from app.statement_lines where statement_id = :s"), {"s": sid})).all()
    portal = next(ln for ln in lines if ln.description.startswith("Client portal"))
    assert portal.quantity == 1 and float(portal.unit_price) == 99

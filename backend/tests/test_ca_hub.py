"""Upload hub (docs/PLAN-CA-DESK-2.md #3): a zip opened safely, every sample file recognised by its columns (no AI for
spreadsheets), filed, ticked off the checklist, the right agent run (GST reconciliation when a 2B and a purchase register
come together), duplicates not stored twice, and the same through the client portal."""
import io
import zipfile

from sqlalchemy import text

from agentry.automations.ca import hub
from agentry.automations.ca.taxdocs import SAMPLES
from agentry.db import tenant_session

ALL = ["ca_filing_tracker", "ca_document_chaser", "ca_tax_docs_reader", "ca_gst_reconciliation", "ca_capital_gains", "ca_bank_classifier",
       "ca_notice_handler", "ca_tds_returns", "excel_desk"]
CLIENT = {"name": "Mehta Traders", "kind": "firm", "pan": "AAKFM1234L", "gstin": "27AAKFM1234L1Z5", "profile": {"gst": True, "business": True}}


def _zip(files: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for n, d in files.items():
            z.writestr(n, d)
    return buf.getvalue()


def test_recognise_and_unpack():
    assert hub.sniff((SAMPLES / "bank_statement_sample.csv").read_bytes(), "text/csv") == "bank_statement"
    assert hub.sniff((SAMPLES / "broker_pnl_sample.csv").read_bytes(), "text/csv") == "broker_pnl"
    assert hub.sniff((SAMPLES / "tds_register_sample.csv").read_bytes(), "text/csv") == "tds_register"
    assert hub.sniff((SAMPLES / "purchase_register_sample.csv").read_bytes(), "text/csv") == "purchase_register"
    assert hub.sniff((SAMPLES / "messy_sales_register_sample.csv").read_bytes(), "text/csv") == "sales_register"
    assert hub.sniff((SAMPLES / "gstr2b_sample.json").read_bytes(), "application/json") == "gstr2b"
    tb = b"Ledger,Group,Debit,Credit\nCapital,Capital Account,,500000\nCash,Current Assets,25000,\nSales,Income,,900000\n"
    assert hub.sniff(tb, "text/csv") == "trial_balance"
    far = b"Asset,Block,Date put to use,Cost,Rate,Depreciation\nLaptop,Computers,01/05/2026,80000,40%,32000\n"
    assert hub.sniff(far, "text/csv") == "fixed_asset_register"
    assert hub.sniff(b"just,some,words\nno,clear,type\n", "text/csv") is None

    files, skipped = hub.unpack([(hub.sample_zip(), "docs.zip", "application/zip")])
    assert len(files) == len(hub.SAMPLE_FILES) and not skipped  # __MACOSX junk ignored, folders flattened
    big = _zip({"zeros.csv": b"0" * 5_000_000, "inner.zip": b"PK", "ok.csv": b"a,b\n1,2\n"})
    files, skipped = hub.unpack([(big, "x.zip", None)])
    assert [f[1] for f in files] == ["ok.csv"]
    assert {s["filename"] for s in skipped} == {"zeros.csv", "inner.zip"}  # compressed too much; zip in a zip
    many, skipped = hub.unpack([(b"a,b\n", f"f{i}.csv", "text/csv") for i in range(hub.MAX_FILES + 3)])
    assert len(many) == hub.MAX_FILES and len(skipped) == 3


async def test_sample_zip_routes_every_file(client, team_org):
    _oid, h = await team_org(ALL)
    cid = (await client.post("/org/ca/clients", headers=h["owner"], json=CLIENT)).json()["id"]
    await client.post("/org/ca/filings", headers=h["owner"], json={"client_id": cid, "kind": "gstr3b", "period": "Oct 2026", "due_on": "2026-11-20"})
    assert (await client.post(f"/org/ca/clients/{cid}/hub/sample", headers=h["viewer"])).status_code == 403
    r = await client.post(f"/org/ca/clients/{cid}/hub/sample", headers=h["owner"])
    assert r.status_code == 201, r.text
    b = r.json()
    by = {f["filename"]: f for f in b["files"]}
    assert by["HDFC statement Oct.csv"]["ran"]["agent"] == "ca_bank_classifier"
    assert by["Zerodha tax P&L FY25-26.csv"]["ran"]["agent"] == "ca_capital_gains"
    assert by["TDS payments Q2.csv"]["ran"]["agent"] == "ca_tds_returns"
    assert by["Day book Apr-Oct.csv"]["ran"]["agent"] == "ca_anomaly_finder"
    assert by["Sales Oct.csv"]["ran"]["agent"] == "ca_gstr1" and by["Sales Oct.csv"]["ticked"]
    assert by["Purchases Oct.csv"]["ran"]["agent"] == by["GSTR2B_Oct2026.json"]["ran"]["agent"] == "ca_gst_reconciliation"
    assert by["IT notice.txt"]["doc_type"] == "notice" and by["IT notice.txt"]["ran"]["agent"] == "ca_notice_handler"
    assert by["Form16.txt"]["doc_type"] == "form16" and by["AIS.txt"]["doc_type"] == "ais"
    assert by["Purchases Oct.csv"]["ticked"]  # the GSTR-3B checklist's purchase register
    assert b["summary"]["filed"] == len(hub.SAMPLE_FILES) and b["summary"]["problems"] == 0, b["files"]
    work = (await client.get(f"/org/ca/clients/{cid}/work", headers=h["owner"])).json()["items"]
    agents = {w["agent"] for w in work}
    assert {"ca_upload_hub", "ca_bank_classifier", "ca_capital_gains", "ca_tds_returns", "ca_anomaly_finder", "ca_gst_reconciliation", "ca_gstr1"} <= agents
    gst = next(w for w in work if w["agent"] == "ca_gst_reconciliation")
    assert gst["title"] == "GST reconciliation Oct 2026"  # period from the 2B file
    again = (await client.post(f"/org/ca/clients/{cid}/hub/sample", headers=h["owner"])).json()
    assert again["summary"]["duplicates"] == len(hub.SAMPLE_FILES) and again["summary"]["filed"] == 0
    x = await client.get(f"/org/ca/work/{b['id']}/sheet.xlsx", headers=h["owner"])
    assert x.status_code == 200


async def test_agents_switched_off_and_bad_files(client, team_org):
    _oid, h = await team_org(["ca_filing_tracker"])
    cid = (await client.post("/org/ca/clients", headers=h["owner"], json=CLIENT)).json()["id"]
    r = await client.post(f"/org/ca/clients/{cid}/hub", headers=h["owner"], files=[
        ("files", ("statement.csv", (SAMPLES / "bank_statement_sample.csv").read_bytes(), "text/csv")),
        ("files", ("song.mp3", b"ID3", "audio/mpeg"))])
    assert r.status_code == 201, r.text
    by = {f["filename"]: f for f in r.json()["files"]}
    assert by["statement.csv"]["status"] == "filed" and "switched on" in by["statement.csv"]["next"]
    assert by["song.mp3"]["status"] == "skipped"
    assert (await client.post("/org/ca/clients/00000000-0000-0000-0000-000000000000/hub/sample", headers=h["owner"])).status_code == 404


async def test_client_portal_many(client, team_org):
    oid, h = await team_org(ALL)
    cid = (await client.post("/org/ca/clients", headers=h["owner"], json=CLIENT)).json()["id"]
    await client.put("/org/ca/portal", headers=h["owner"], json={"enabled": True})
    token = (await client.post(f"/org/ca/clients/{cid}/portal", headers=h["owner"])).json()["url"].rsplit("/", 1)[1]
    z = _zip({"bank.csv": (SAMPLES / "bank_statement_sample.csv").read_bytes(), "tds.csv": (SAMPLES / "tds_register_sample.csv").read_bytes()})
    r = await client.post(f"/public/portal/{token}/files/many", files=[("files", ("from-me.zip", z, "application/zip")),
                                                                      ("files", ("broker.csv", (SAMPLES / "broker_pnl_sample.csv").read_bytes(), "text/csv"))])
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["received"] == 3 and {f["taken_as"] for f in body["files"]} == {"Bank statement", "Payments register with TDS", "Broker capital gains statement"}
    assert "ran" not in body["files"][0]  # the client sees what each file was taken as, not the firm's agents
    async with tenant_session(oid) as conn:
        srcs = set((await conn.execute(text("select source from app.ca_files"))).scalars())
        runs = (await conn.execute(text("select count(*) from app.ca_work where agent <> 'ca_upload_hub'"))).scalar_one()
    assert srcs == {"client_portal"} and runs == 3


async def test_website_box(client):
    r = (await client.post("/public/playground/upload-hub", headers={"x-forwarded-for": "203.0.113.79"}, json={"input": {}})).json()
    by = {f["filename"]: f for f in r["files"]}
    assert by["GSTR2B_Oct2026.json"]["agent"] == by["Purchases Oct.csv"]["agent"] == "ca_gst_reconciliation"
    assert by["Day book Apr-Oct.csv"]["agent"] == "ca_anomaly_finder" and by["IT notice.txt"]["recognised"] == "Tax notice"
    assert "columns" in (await client.get("/public/sources/ca-upload-hub")).json()["basis"]

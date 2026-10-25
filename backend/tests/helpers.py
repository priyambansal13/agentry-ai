"""Shared helpers for tests that build invoices in a fresh organisation (fixture `org` in conftest.py)."""
import csv
import io
from datetime import date

from sqlalchemy import text

from agentry.db import tenant_session
from agentry.invoices import enroll_open, map_columns_heuristic, normalise_rows, parse_file, upsert_invoices


def csv_bytes(rows: list[dict]) -> bytes:
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=list(rows[0]))
    w.writeheader()
    w.writerows(rows)
    return buf.getvalue().encode()



async def import_invoices(org: str, rows: list[dict]) -> dict:
    data = parse_file(csv_bytes(rows), "inv.csv")
    clean, issues = normalise_rows(data, map_columns_heuristic(list(data[0])), "INR")
    async with tenant_session(org) as conn:
        r = await upsert_invoices(conn, org, clean, source="test")
        r["enrolled"] = await enroll_open(conn, org)
    return r | {"issues": issues}


def inv(number: str, due: date, amount: int = 45000, paid: int = 0, email: str = "rohan@northstar.example") -> dict:
    return {"Invoice": number, "Company": "Northstar Realty", "Contact": "Rohan Mehta", "Email": email, "Phone": "+91-90000-00001",
            "Amount": amount, "Amount paid": paid, "Due date": due.isoformat()}



async def enrollment_for(org: str, number: str) -> str:
    async with tenant_session(org) as conn:
        return str((await conn.execute(text("""select e.id from app.sequence_enrollments e join app.invoices i on i.id = e.subject_id
            where i.number = :n order by e.created_at desc limit 1"""), {"n": number})).scalar_one())



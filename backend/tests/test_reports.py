"""Monthly results report email: right people, right numbers for what the client bought."""
from datetime import date

from agentry import reports
from agentry.automations.inbox_triage.ingest import ingest_email
from agentry.db import tenant_session
from agentry.events import emit


async def test_monthly_report_email(team_org, monkeypatch):
    oid, _h = await team_org(["inbox_triage"])
    sent = []
    monkeypatch.setattr(reports, "send_email", lambda to, subject, body: sent.append((to, subject, body)))
    await ingest_email(oid, sender="a@b.example", subject="hello", body="hi", thread_ref="local:r1")
    async with tenant_session(oid) as conn:  # 30 emails triaged in September
        for _ in range(30):
            await emit(conn, oid, "email.triaged", {"category": "Client"})
        await conn.execute(__import__("sqlalchemy").text(
            "update app.events set occurred_at = '2026-09-15' where type = 'email.triaged' and org_id = :o"), {"o": oid})
    n = await reports.send_monthly(oid, today=date(2026, 10, 2))
    who = sorted(to.split("-")[0] for to, _, _ in sent)
    assert n == 2 and who == ["manager", "owner"]  # opted in by default; finance/viewer can opt in
    subject, body = sent[0][1], sent[0][2]
    assert subject == "Your September 2026 results from Agentry"  # no ROI line without a statement
    assert "Emails sorted: 30 (about 1 hour given back)" in body and "Appointments" not in body and "/reports?month=2026-09" in body

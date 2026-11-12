"""The try-it boxes on the website's agent pages (agentry/playground.py, /public/playground): the calculations run the
CA engines on the samples and on edited rows; the AI boxes run their prompts (mock answers here), count against the
visitor's daily limit and the website's budget, and record what they cost."""
import random

import pytest
from sqlalchemy import text

from agentry import playground
from agentry.config import settings
from agentry.db import system_session


def visitor() -> dict:
    return {"x-forwarded-for": f"10.{random.randint(1, 250)}.{random.randint(1, 250)}.{random.randint(1, 250)}"}


@pytest.fixture(autouse=True)
def public_sites(monkeypatch):
    monkeypatch.setattr("agentry.knowledge._check_public", lambda url: None)  # the sample sites are *.example


@pytest.mark.parametrize("kind", ["itr", "capital-gains", "tds", "audit-3cd", "gst", "bank", "tax-docs"])
async def test_calculations_run_on_their_samples(client, kind):
    s = (await client.get(f"/public/playground/{kind}/sample")).json()
    r = await client.post(f"/public/playground/{kind}", headers=visitor(), json={"input": s})
    assert r.status_code == 200, r.text


async def test_calculations_answer_like_the_portal(client):
    ip = visitor()
    itr = (await client.post("/public/playground/itr", headers=ip, json={"input": playground.ITR_SAMPLE})).json()
    assert itr["better"] in ("old", "new") and itr["new"]["tax_liability"] > 0 and itr["itr_form"].startswith("ITR-")
    rows = (await client.get("/public/playground/audit-3cd/sample")).json()["rows"]
    audit = (await client.post("/public/playground/audit-3cd", headers=ip, json={"input": {"rows": rows, "fy_start": 2025}})).json()
    assert any(c["clause"] == "40A(3)" for c in audit["clauses"])  # the sample's two cash payments on one day
    gst = (await client.post("/public/playground/gst", headers=ip, json={"input": (await client.get("/public/playground/gst/sample")).json()})).json()
    assert gst["itc_at_risk"] > 0 and gst["messages"] and "GSTR-2B" in gst["messages"][0]["message"]
    docs = (await client.post("/public/playground/tax-docs", headers=ip, json={"input": {"form16_tds": 230000, "ais_interest": 52310}})).json()
    assert docs["points"][0]["kind"] == "tds_mismatch"  # Form 16 edited to differ from AIS
    cal = (await client.post("/public/playground/calendar", headers=ip, json={"input": {"client_kind": "company", "profile": {"gst": True, "tds": True}}})).json()
    assert cal["deadlines"] and all(d["days_left"] >= 0 for d in cal["deadlines"]) and "reminder" in cal["deadlines"][0]
    ch = (await client.post("/public/playground/chaser", headers=ip, json={"input": {"profile": {"salaried": True}, "received": ["form16"]}})).json()
    assert "Form 16 from your employer" not in ch["missing"] and ch["reminders"][0]["day"] == 0
    ren = (await client.post("/public/playground/renewals", headers=ip, json={"input": {"amount": 4500, "due_on": "2027-01-20", "every": "yearly"}})).json()
    assert [x["label"] for x in ren["reminders"]] == ["30 days before", "7 days before", "1 day before"] and ren["next_due"] == "2028-01-20"


async def test_bad_rows_are_explained(client):
    r = await client.post("/public/playground/tds", headers=visitor(), json={"input": {"rows": [["a", "b"], ["1", "2"]]}})
    assert r.status_code == 422 and "couldn't read that" in r.json()["detail"]
    assert (await client.post("/public/playground/nope", headers=visitor(), json={"input": {}})).status_code == 404


async def test_ai_boxes_run_and_count(client):
    ip = visitor()
    cases = {
        "lead-research": {"website": "kapoorsmilestudio.example", "message": "Do you do implants?"},
        "cold-email": {"website": "kapoorsmilestudio.example", "offer": "patient reminders on WhatsApp"},
        "inbox": {"from": "accounts@kaveritextiles.co", "subject": "Updated bank details", "body": "Please pay invoice 2231 to our new bank account from today."},
        "doc": {"kind": "sop", "brief": "How the front desk opens the clinic every morning and checks appointments"},
        "festival": {"business": "SmileCraft Dental", "offer": "Free check-up this week"},
        "content": (await client.get("/public/playground/content/sample")).json(),
        "video": {"business": "SmileCraft Dental", "topic": "why your gums bleed when you brush"},
    }
    for kind, inp in cases.items():
        r = await client.post(f"/public/playground/{kind}", headers=ip, json={"input": inp})
        assert r.status_code == 200, (kind, r.text)
        assert "cost_usd" in r.json()
    assert (await client.post("/public/playground/inbox", headers=ip, json={"input": cases["inbox"]})).json()["risk"]  # changed bank details
    r = await client.post("/public/playground/video", headers=ip, json={"input": cases["video"]})
    assert r.status_code == 429  # 8 AI tries a day per visitor
    async with system_session() as conn:
        n = (await conn.execute(text("select count(*) from app.public_tries where created_at > now() - interval '1 minute'"))).scalar_one()
    assert n >= 8


async def test_ai_boxes_respect_the_budget(client, monkeypatch):
    monkeypatch.setattr(settings, "audit_daily_budget_usd", 0.0)
    r = await client.post("/public/playground/video", headers=visitor(), json={"input": {"topic": "brushing", "business": "X"}})
    assert r.status_code == 503


async def test_ai_boxes_need_the_human_check(client, monkeypatch):
    monkeypatch.setattr(settings, "turnstile_secret", "set")
    r = await client.post("/public/playground/video", headers=visitor(), json={"input": {"topic": "brushing"}})
    assert r.status_code == 400
    calc = await client.post("/public/playground/renewals", headers=visitor(), json={"input": {}})
    assert calc.status_code == 200  # calculations don't need it


async def test_cv_score_hides_personal_details(client):
    cv = ("Asha Verma\nasha@example.com\nMarried, female, age: 29\nFront desk executive, 4 years at Sunrise Clinic.\n"
          "Managed appointments on Practo and WhatsApp for 3 doctors. Fluent in Hindi and Marathi. Handled billing in Tally.")
    r = await client.post("/public/playground/hiring", headers=visitor(), json={"input": {"title": "Clinic receptionist", "must_have": "appointments, Tally", "cv": cv}})
    assert r.status_code == 200, r.text
    assert "married" in r.json()["hidden"] and all(s["quote"].lower() in cv.lower() for s in r.json()["strengths"])

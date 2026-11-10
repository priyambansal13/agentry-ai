"""AI visibility (PLAN-TRY-IT-AND-AI-VISIBILITY B) and the shared AI search reader (ai_search.py): who the assistants
name, matched to the business and its competitors, scored, with fixes; mock answers in tests (no cost)."""
from sqlalchemy import text

from agentry import ai_search
from agentry.automations import ai_visibility as vis
from agentry.db import tenant_session


def test_matching_names_and_domains():
    me = {"name": "SmileCraft Dental", "aliases": ["Smile Craft"], "website": "https://www.smilecraft.example"}
    assert ai_search.is_same("SmileCraft Dental Clinic, Indiranagar", me)
    assert ai_search.is_same("Smile Craft", me)
    assert ai_search.is_same("smilecraft", me)  # the website's name
    assert not ai_search.is_same("Smile Lounge Dental", me)
    assert not ai_search.is_same("Dental", me)
    assert ai_search.domain_root("https://www.practo.com/x") == "practo"
    assert vis.parse_competitor("Dr Rao Dental — https://drrao.example") == {"name": "Dr Rao Dental", "website": "https://drrao.example"}
    assert vis.parse_competitor("Smile Lounge")["website"] is None
    assert ai_search.bold_names("1. **Clove Dental**: good\n2. **Smile Lounge** fine\n**Note**: x") == [
        {"name": "Clove Dental", "said": ""}, {"name": "Smile Lounge", "said": ""}]
    qs = ai_search.questions_for("dentist", "Bengaluru", "Indiranagar")
    assert len(qs) == 15 and all("dentist" in q.lower() for q in qs) and "Indiranagar" in qs[0]


def test_score_counts_share_and_sources():
    comps = [{"name": "Clove Dental", "website": None}, {"name": "Dr Rao", "website": None}]
    answers = [
        {"engine": "chatgpt", "question": "q1", "citations": ["https://www.practo.com/a"], "error": None,
         "named": [{"name": "Clove Dental", "position": 1, "who": "Clove Dental"}, {"name": "Us", "position": 2, "who": "me"}]},
        {"engine": "gemini", "question": "q1", "citations": ["https://practo.com/b", "https://justdial.com/c"], "error": None,
         "named": [{"name": "Someone Else", "position": 1, "who": None}]},
        {"engine": "gemini", "question": "q2", "citations": [], "error": "RateLimitError", "named": []},
    ]
    s = ai_search.score(answers, comps)
    assert (s["asked"], s["failed"], s["named"], s["rate"], s["avg_position"]) == (2, 1, 1, 50, 2.0)
    assert s["engines"]["chatgpt"]["rate"] == 100 and s["engines"]["gemini"]["rate"] == 0
    assert {x["name"]: x["mentions"] for x in s["share"]} == {"Clove Dental": 1, "You": 1, "Dr Rao": 0}
    assert s["sources"][0] == {"site": "practo.com", "times": 2}
    assert s["named_instead"] == [{"name": "Someone Else", "mentions": 1}]


async def test_setup_check_score_fixes_and_limits(client, team_org):
    oid, h = await team_org(["ai_visibility"])
    r = (await client.get("/org/ai-visibility", headers=h["owner"])).json()
    assert r["ready"] is False and r["test_mode"] is True and r["latest"] is None
    assert (await client.post("/org/ai-visibility/check", headers=h["owner"])).status_code == 409  # nothing to ask yet
    body = {"service": "dentist", "city": "Bengaluru", "area": "Indiranagar", "other_names": ["Team Test"],
            "competitors": ["Clove Dental — clovedental.example", "Dr Rao Dental"]}
    assert (await client.put("/org/ai-visibility/setup", headers=h["staff"], json=body)).status_code == 403
    r = (await client.put("/org/ai-visibility/setup", headers=h["owner"], json=body)).json()
    assert len(r["questions"]) == 15 and r["competitors"][0] == {"name": "Clove Dental", "website": "clovedental.example"}
    assert (await client.put("/org/ai-visibility/setup", headers=h["owner"], json={"questions": ["best dentist in Indiranagar", "  "]})).json()["questions"] == ["best dentist in Indiranagar"]
    await client.put("/org/ai-visibility/setup", headers=h["owner"], json={"questions": []})  # back to the suggested ones

    rid = (await client.post("/org/ai-visibility/check", headers=h["owner"])).json()["run_id"]
    assert (await client.post("/org/ai-visibility/check", headers=h["owner"])).status_code == 409  # one at a time
    out = await vis.run_check(oid, rid)
    assert out["status"] == "done"
    sc = out["score"]
    assert sc["asked"] == 15 * 2 * 3 and 0 < sc["named"] < sc["asked"]  # mock: 2 assistants, 3 repeats, named about half the time
    assert {x["name"] for x in sc["share"]} >= {"You", "Clove Dental", "Dr Rao Dental"}
    kinds = [f["kind"] for f in sc["fixes"]]
    assert "website" in kinds and "listings" in kinds
    assert any("LocalBusiness" in (f.get("code") or "") for f in sc["fixes"])
    over = (await client.get("/org/ai-visibility", headers=h["viewer"])).json()
    assert over["latest"]["score"]["rate"] == sc["rate"] and over["manual_left"] == 1 and over["can_edit"] is False
    run = (await client.get(f"/org/ai-visibility/runs/{rid}", headers=h["viewer"])).json()
    assert len(run["answers"]) == 90 and any(a["me_position"] for a in run["answers"])

    rid2 = (await client.post("/org/ai-visibility/check", headers=h["manager"])).json()["run_id"]
    await vis.run_check(oid, rid2)
    r = await client.post("/org/ai-visibility/check", headers=h["owner"])
    assert r.status_code == 409 and "a month" in r.json()["detail"]
    assert (await client.post("/org/ai-visibility/write-page", headers=h["owner"], json={"question": "best dentist"})).status_code == 409


async def test_monthly_check_leaves_a_needs_you_card(team_org):
    oid, _h = await team_org(["ai_visibility"])
    async with tenant_session(oid) as conn:
        await conn.execute(text("update app.automation_instances set config = config || cast(:c as jsonb) where template_key = 'ai_visibility'"),
                           {"c": '{"service": "AC repair", "city": "Pune"}'})
    assert await vis.monthly_jobs() >= 1
    async with tenant_session(oid) as conn:
        rid = (await conn.execute(text("select id::text from app.ai_vis_runs where trigger = 'monthly'"))).scalar_one()
    assert (await vis.run_check(oid, rid))["status"] == "done"
    async with tenant_session(oid) as conn:
        card = (await conn.execute(text("select title, body from app.approvals where automation_key = 'ai_visibility'"))).first()
    assert card and "AI assistants named you in" in card.body

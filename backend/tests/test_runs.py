"""Agent runs: model calls add up per run, failures are recorded, long jobs share one run, the real agents record runs,
and costs are visible to Agentry staff only."""
import pytest
from conftest import expect
from sqlalchemy import text

from agentry.db import tenant_session
from agentry.llm.gateway import complete
from agentry.runs import current, run

ALL = ("owner", "manager", "staff", "finance", "viewer", "agentry")


async def runs_of(oid: str) -> list[dict]:
    async with tenant_session(oid) as conn:
        return [dict(r) for r in (await conn.execute(text("select * from app.agent_runs order by started_at"))).mappings()]


async def test_a_run_collects_its_model_calls_steps_and_failures(team_org):
    oid, _h = await team_org(["inbox_triage"])
    async with run(oid, "inbox_triage", "test.thing", subject=("message", "m1")) as r:
        await complete("fast", [{"role": "user", "content": "hi"}], org_id=oid, prompt_key="t", prompt_version="v1", mock_response="ok")
        await complete("writer", [{"role": "user", "content": "hi"}], org_id=oid, prompt_key="t", prompt_version="v1", mock_response="ok")
        r.step("did a thing", count=2)
    await complete("fast", [{"role": "user", "content": "outside"}], org_id=oid, prompt_key="t", prompt_version="v1", mock_response="ok")
    with pytest.raises(RuntimeError):
        async with run(oid, "inbox_triage", "test.broken"):
            raise RuntimeError("model said no")
    ok, bad = await runs_of(oid)
    assert ok["status"] == "ok" and ok["model_calls"] == 2 and ok["ended_at"] is not None
    assert [s["name"] for s in ok["steps"]] == ["did a thing"] and ok["steps"][0]["detail"] == {"count": 2}
    assert bad["status"] == "failed" and bad["error"] == "RuntimeError: model said no"
    current().step("outside any run")  # harmless


async def test_a_long_job_is_one_run_across_steps(team_org):
    oid, _h = await team_org(["content_repurposing"])
    for i in range(3):
        async with run(oid, "content_repurposing", "content.source", key="content:abc", final=i == 2) as r:
            await complete("writer", [{"role": "user", "content": str(i)}], org_id=oid, prompt_key="t", prompt_version="v1", mock_response="ok")
            r.step(f"part {i}")
    (one,) = await runs_of(oid)
    assert one["status"] == "ok" and one["model_calls"] == 3 and [s["name"] for s in one["steps"]] == ["part 0", "part 1", "part 2"]


async def test_agents_record_runs_and_costs_are_staff_only(client, team_org, monkeypatch, tmp_path):
    from test_inbox_batch_a import triaged

    from agentry.automations.content import pipeline
    from agentry.config import settings
    monkeypatch.setattr(settings, "content_transcriber", "mock")
    monkeypatch.setattr(settings, "content_dir", str(tmp_path))
    oid, h = await team_org(["inbox_triage", "content_repurposing", "website_chat"])
    await triaged(oid, sender="client@acme.example", subject="Quote please", body="Can you send a quote for 3 laptops?")
    sid = (await client.post("/org/content/sources/sample", headers=h["owner"])).json()["id"]
    await pipeline.content_process_source(oid, sid)
    kinds = {(r["agent"], r["kind"], r["status"]) for r in await runs_of(oid)}
    assert ("content_repurposing", "content.source", "ok") in kinds
    content = next(r for r in await runs_of(oid) if r["kind"] == "content.source")
    assert content["model_calls"] >= 30 and [s["name"] for s in content["steps"]] == ["moments found", "posts written"]
    owner = (await client.get("/org/runs?agent=content_repurposing", headers=h["owner"])).json()["items"]
    assert owner and "cost_usd" not in owner[0] and owner[0]["status"] == "ok"
    staff = (await client.get("/org/runs?agent=content_repurposing", headers=h["agentry"])).json()["items"]
    assert "cost_usd" in staff[0] and staff[0]["model_calls"] >= 30
    got = {r: (await client.get(f"/hq/orgs/{oid}/agent-costs", headers=h[r])).status_code for r in ALL}
    expect(got, owner=403, manager=403, staff=403, finance=403, viewer=403, agentry=200)
    costs = (await client.get(f"/hq/orgs/{oid}/agent-costs", headers=h["agentry"])).json()
    assert {a["agent"] for a in costs["agents"]} >= {"content_repurposing"}

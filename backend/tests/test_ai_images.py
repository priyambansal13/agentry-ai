"""AI images (ROADMAP-V2 8.7): off by default; when on, one checked background per moment behind its cards, under a cap,
with the cost recorded; images showing people or text are never used."""
import io

import pytest
from PIL import Image
from sqlalchemy import text

from agentry.automations.content import ai_images, images, pipeline
from agentry.config import settings
from agentry.db import tenant_session


@pytest.fixture(autouse=True)
def content_test_mode(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "content_transcriber", "mock")
    monkeypatch.setattr(settings, "content_publisher", "mock")
    monkeypatch.setattr(settings, "content_dir", str(tmp_path / "content"))
    monkeypatch.setattr(settings, "model_image", "mock")


async def podcast(client, h, oid) -> dict:
    sid = (await client.post("/org/content/sources/sample", headers=h["owner"])).json()["id"]
    assert await pipeline.content_process_source(oid, sid) == "ready"
    return (await client.get(f"/org/content/sources/{sid}", headers=h["owner"])).json()


async def test_off_by_default_no_backgrounds(client, team_org):
    oid, h = await team_org(["content_repurposing"])
    await podcast(client, h, oid)
    async with tenant_session(oid) as conn:
        assert (await conn.execute(text("select count(*) from app.content_moments where ai_bg_path is not null"))).scalar_one() == 0
    kit = (await client.get("/org/content/brand", headers=h["owner"])).json()
    assert kit["ai_images"] is False and kit["image_usage"]["test_mode"] is True
    r = await client.post(f"/org/content/moments/{(await podcast(client, h, oid))['moments'][0]['id']}/background", headers=h["owner"])
    assert r.status_code == 409


async def test_on_one_background_per_moment_under_the_cards(client, team_org):
    oid, h = await team_org(["content_repurposing"])
    r = await client.put("/org/content/brand", headers=h["owner"], json={"ai_images": True, "image_style": "pastel watercolour"})
    assert r.status_code == 200
    assert (await client.put("/org/content/brand", headers=h["staff"], json={"ai_images": False})).status_code == 403
    s = await podcast(client, h, oid)
    async with tenant_session(oid) as conn:
        bgs = (await conn.execute(text("select ai_bg_path from app.content_moments where ai_bg_path is not null"))).scalars().all()
    assert len(bgs) == 10  # one per moment, shared by its 3 platform cards
    img = await client.get(f"/org/content/posts/{s['posts'][0]['id']}/image", headers=h["owner"])
    assert Image.open(io.BytesIO(img.content)).size in ((1080, 1080), (1200, 675))
    mid = s["moments"][0]["id"]
    r = await client.post(f"/org/content/moments/{mid}/background", headers=h["owner"])
    assert r.status_code == 200 and r.json()["redrawn"] == 3
    assert (await client.post(f"/org/content/moments/{mid}/background", headers=h["staff"])).status_code == 403


def test_prompt_rules_and_the_background_changes_the_card(tmp_path):
    p = ai_images.prompt_for({"image_style": "ink sketch"}, {"topic": "Fix small problems early"})
    assert "ink sketch" in p and "Fix small problems early" in p and "No people" in p and "No text" in p
    assert ai_images.DEFAULT_STYLE in ai_images.prompt_for({}, {"quote": "x"})
    bg = tmp_path / "bg.png"
    bg.write_bytes(ai_images.mock_png({}, "seed"))
    kit = {"primary_color": "#1f2a1a", "accent_color": "#c8f04a"}
    plain = images.render("instagram", "Hello there", "Asha", kit)
    with_bg = images.render("instagram", "Hello there", "Asha", kit, background=bg)
    assert plain != with_bg and Image.open(io.BytesIO(with_bg)).size == (1080, 1080)


async def test_unsafe_images_are_dropped_and_the_cap_holds(team_org, monkeypatch):
    oid, _h = await team_org(["content_repurposing"])
    monkeypatch.setattr(ai_images, "live", lambda: True)
    calls = []

    async def fake_generate(org_id, prompt, kit):
        calls.append(prompt)
        return ai_images.mock_png(kit, prompt), 0.006

    async def always_people(org_id, png):
        return True
    monkeypatch.setattr(ai_images, "generate", fake_generate)
    monkeypatch.setattr(ai_images, "shows_people_or_text", always_people)
    kit = {"ai_images": True, "images_per_month": 40}
    async with tenant_session(oid) as conn:
        out = await ai_images.background(conn, oid, kit, {"id": "00000000-0000-0000-0000-000000000001", "topic": "x"})
    assert out is None and len(calls) == 2 and "Absolutely no people" in calls[1]  # retried once, then not used

    async def full(conn):
        return {"images": 40}
    monkeypatch.setattr(ai_images, "month_usage", full)
    calls.clear()
    async with tenant_session(oid) as conn:
        assert await ai_images.background(conn, oid, kit, {"id": "00000000-0000-0000-0000-000000000002", "topic": "x"}) is None
    assert calls == []  # over this month's cap: nothing generated

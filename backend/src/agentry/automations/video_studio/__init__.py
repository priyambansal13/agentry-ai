"""AI video studio (docs/flows/agents/ai-video-studio.md): short videos planned, generated with Veo, branded, reviewed
and published to YouTube, on a schedule or on demand.

    plan      the writer model plans a Short from the business's topics, services and brand (never a topic used in the
              last 60 days): title, description, hashtags, hook, 1-4 scenes of 8 s (Veo prompt + caption)
    check     rules (no guarantees, prices, "best", ...) + a second model's opinion; one rewrite, else a person decides
    budget    the cost is estimated before anything is generated; a video that would pass the month's budget is skipped
    generate  one Veo 3.1 render per scene (OpenAI retired Sora in Sep 2026), polled every 15 s by a durable workflow (up to 12 minutes), then downloaded
    compose   scenes joined at 1080x1920, the hook as a banner for 3 s, a caption per scene, the brand end card
    publish   approval mode: a review card (watch it, Approve publishes); live: published straight away; YouTube as a
              Short (#Shorts), privacy as set, marked as synthetic media
The plan is written by OpenAI first (Gemini as the fallback; settings: planner). Test mode (no key for the chosen video
model: AGENTRY_VIDEO_API_KEY or GEMINI_API_KEY with Veo access): scenes are branded test cards, free; usage events are marked mock (not billed).
"""
import json
import re
import shutil
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal
from zoneinfo import ZoneInfo

from dbos import DBOS
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from agentry.automations import AutomationTemplate, register
from agentry.automations.content import brand, clips
from agentry.automations.video_studio import gen, veo
from agentry.config import settings
from agentry.db import system_session, tenant_session
from agentry.events import emit
from agentry.llm.gateway import AllModelsFailed, complete
from agentry.llm.prompts import load
from agentry.worker.handlers import on

DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
SCENE_S = 8
POLL_S, POLL_MAX = 15, 48
RISKY = re.compile(r"\b(guarantee[sd]?|100\s?%|cure[sd]?|risk[- ]free|best in|#1|no\.? ?1|cheapest|lowest price|free forever|miracle|"
                   r"overnight results|doubles? your|clinically proven)\b|(₹|rs\.?|inr)\s?\d", re.IGNORECASE)


class VideoConfig(BaseModel):
    topics: list[str] = Field(default_factory=list, title="Topics to make videos about",
                              description="e.g. 'How we clean an AC', '3 signs your teeth need a check-up'. Empty: ideas from your services.",
                              json_schema_extra={"editable_by": "client"})
    style: str = Field("realistic, bright natural light, warm and friendly, people at work", title="Visual style",
                       json_schema_extra={"editable_by": "client"})
    language: str = Field("English", title="Language of titles and captions", description="English, Hindi or Hinglish",
                          json_schema_extra={"editable_by": "client"})
    call_to_action: str | None = Field(None, title="Call to action", description="e.g. 'Book on WhatsApp: +91 98100 00011'",
                                       json_schema_extra={"editable_by": "client"})
    days: list[str] = Field(default_factory=lambda: ["mon", "wed", "fri"], title="Days to make a video", json_schema_extra={"editable_by": "client"})
    time: str = Field("11:00", pattern=r"^\d{2}:\d{2}$", title="Time (your timezone)", json_schema_extra={"editable_by": "client"})
    scenes: int = Field(2, ge=1, le=4, title="Scenes per video (8 seconds each)", json_schema_extra={"editable_by": "client"})
    provider: Literal["google"] = Field("google", title="Video model", description="Google Veo 3.1 (OpenAI retired Sora in Sep 2026).",
                                        json_schema_extra={"editable_by": "agentry"})
    quality: Literal["fast", "standard"] = Field("fast", title="Quality", description="fast: Veo 3.1 fast. standard: Veo 3.1.",
                                                 json_schema_extra={"editable_by": "agentry"})
    planner: Literal["openai", "gemini"] = Field("openai", title="AI that plans the videos (the other is the fallback)",
                                                 json_schema_extra={"editable_by": "agentry"})
    privacy: Literal["public", "unlisted", "private"] = Field("public", title="YouTube visibility", json_schema_extra={"editable_by": "client"})
    monthly_budget_usd: float = Field(30, ge=0, le=5000, title="Monthly video budget (USD)", json_schema_extra={"editable_by": "agentry"})
    cost_per_second_fast: float = Field(0.15, ge=0, title="Veo fast: USD per second", json_schema_extra={"editable_by": "agentry"})
    cost_per_second_standard: float = Field(0.40, ge=0, title="Veo standard: USD per second", json_schema_extra={"editable_by": "agentry"})


register(AutomationTemplate(
    key="video_studio", name="AI video studio",
    description="Short videos planned from your business, made with Veo, branded, checked and posted to YouTube on a schedule.",
    config_model=VideoConfig, metrics=("videos_published",),
))


class VideoError(RuntimeError):
    pass


async def settings_of(conn: AsyncConnection) -> tuple[str | None, dict]:
    row = (await conn.execute(text("select status, config from app.automation_instances where template_key = 'video_studio'"))).first()
    return (row.status, VideoConfig(**(row.config or {})).model_dump()) if row else (None, VideoConfig().model_dump())


def estimate(cfg: dict) -> float:
    return round(cfg["scenes"] * SCENE_S * gen.rate(cfg), 2)


async def spent_this_month(conn: AsyncConnection, now: datetime) -> float:
    start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    return float((await conn.execute(text("""select coalesce(sum(cost_usd), 0) from app.ai_videos where created_at >= :s
        and status not in ('skipped','needs_attention','rejected')"""), {"s": start})).scalar_one())


def folder(org_id: str, vid: str) -> Path:
    p = Path(settings.content_dir) / org_id / "videos" / vid
    p.mkdir(parents=True, exist_ok=True)
    return p


def resolve(rel: str | None) -> Path | None:
    if not rel:
        return None
    root = Path(settings.content_dir).resolve()
    p = (root / rel).resolve()
    return p if p.is_relative_to(root) and p.is_file() else None


async def request(conn: AsyncConnection, org_id: str, *, topic: str | None, trigger: str = "manual", slot: str | None = None,
                  user_id: str | None = None) -> str | None:
    """Queue a video (None if this schedule slot already has one)."""
    vid = (await conn.execute(text("""insert into app.ai_videos (org_id, trigger, slot, topic, created_by) values (:o, :t, :s, :tp, :u)
        on conflict (org_id, slot) do nothing returning id::text"""), {"o": org_id, "t": trigger, "s": slot, "tp": (topic or "").strip()[:200] or None,
                                                                         "u": user_id})).scalar_one_or_none()
    if vid:
        await emit(conn, org_id, "video.requested", {"video_id": vid, "trigger": trigger})
    return vid


async def _set(org_id: str, vid: str, **cols: object) -> None:
    sets = ", ".join(f"{k} = cast(:{k} as jsonb)" if k in ("plan", "checks", "ops", "publish") else f"{k} = :{k}" for k in cols)
    vals = {k: json.dumps(v) if k in ("plan", "checks", "ops", "publish") else v for k, v in cols.items()}
    async with tenant_session(org_id) as conn:
        await conn.execute(text(f"update app.ai_videos set {sets}, updated_at = now() where id = cast(:id as uuid)"), vals | {"id": vid})


async def _card(conn: AsyncConnection, org_id: str, vid: str, title: str, body: str) -> None:
    await conn.execute(text("""insert into app.approvals (org_id, kind, automation_key, title, body, payload)
        values (:o, 'video_review', 'video_studio', :t, :b, cast(:p as jsonb))"""), {"o": org_id, "t": title[:200], "b": body, "p": json.dumps({"video_id": vid})})


# ---------- plan and check ----------

def rule_problems(plan: dict, scenes: int) -> list[str]:
    out = []
    if not plan.get("title") or len(plan["title"]) > 100:
        out.append("the title is missing or too long")
    if not isinstance(plan.get("scenes"), list) or len(plan["scenes"]) != scenes:
        out.append(f"there must be exactly {scenes} scene(s)")
    words = " ".join([plan.get("title") or "", plan.get("description") or "", plan.get("hook") or "",
                      *[s.get("caption") or "" for s in plan.get("scenes") or [] if isinstance(s, dict)]])
    if m := RISKY.search(words):
        out.append(f"risky wording: \"{m.group(0)}\" (no guarantees, prices or superlatives the business hasn't given)")
    for i, s in enumerate(plan.get("scenes") or []):
        if not isinstance(s, dict) or len((s.get("prompt") or "").split()) < 15:
            out.append(f"scene {i + 1} needs a fuller prompt")
    return out


def _mock_plan(topic: str, scenes: int, business: str, cta: str | None) -> dict:
    return {"topic": topic, "title": f"{topic} | {business}"[:70], "description": f"A quick look at {topic.lower()}.\n{cta or ''}".strip(),
            "hashtags": ["#Shorts", "#SmallBusiness", "#" + re.sub(r"\W", "", business)[:20]], "hook": topic[:50],
            "scenes": [{"prompt": f"Scene {i + 1} about {topic}: a friendly professional at work in a bright, clean workspace, medium shot, slow push-in, "
                                  "soft natural light, warm mood, realistic style, gentle ambient sound of the workplace.",
                        "caption": f"{topic}: part {i + 1}"[:60]} for i in range(scenes)]}


async def context(conn: AsyncConnection, org_id: str, cfg: dict) -> dict:
    business = (await conn.execute(text("select name from auth.organization where id = :o"), {"o": org_id})).scalar_one_or_none() or "the business"
    prof = (await conn.execute(text("select profile, website, industry_pack from app.org_settings"))).mappings().first() or {}
    services = list((await conn.execute(text("select name from app.services order by name limit 20"))).scalars())
    recent = list((await conn.execute(text("""select topic from app.ai_videos where topic is not null and created_at > now() - interval '60 days'
        and status not in ('skipped','rejected') order by created_at desc limit 30"""))).scalars())
    kit = await brand.get_kit(conn, org_id)
    about = ((prof.get("profile") or {}).get("about") or (prof.get("profile") or {}).get("description") or prof.get("industry_pack") or "")
    return {"business": business, "about": str(about)[:600] or f"a {prof.get('industry_pack') or 'local'} business", "services": ", ".join(services) or "(not listed)",
            "recent": recent, "kit": kit}


async def plan_video(org_id: str, vid: str) -> dict:
    """Plan + check. Returns {"status": "generating" | "needs_attention" | "skipped", ...}."""
    async with tenant_session(org_id) as conn:
        _status, cfg = await settings_of(conn)
        v = (await conn.execute(text("select topic from app.ai_videos where id = cast(:i as uuid)"), {"i": vid})).mappings().one()
        ctx = await context(conn, org_id, cfg)
        cost = estimate(cfg)
        spent = await spent_this_month(conn, datetime.now(UTC))
        if cfg["monthly_budget_usd"] and spent + cost > cfg["monthly_budget_usd"]:
            await conn.execute(text("update app.ai_videos set status = 'skipped', error = :e where id = cast(:i as uuid)"),
                               {"e": f"this month's budget (${cfg['monthly_budget_usd']:.0f}) would be passed: ${spent:.2f} spent, this video ~${cost:.2f}", "i": vid})
            await _card(conn, org_id, vid, "A video was skipped: the monthly budget is reached",
                        f"${spent:.2f} of ${cfg['monthly_budget_usd']:.0f} used. Raise the budget in the AI video studio settings to keep going.")
            return {"status": "skipped"}
    ideas = [t for t in cfg["topics"] if t.lower() not in {r.lower() for r in ctx["recent"]}] or cfg["topics"]
    topic = v["topic"] or (ideas[0] if ideas else None)
    prompt, check = load("video_plan"), load("video_check")
    feedback, problems, plan = "", [], {}
    for attempt in range(2):
        vars_ = {"business": ctx["business"], "about": ctx["about"], "services": ctx["services"], "handle": ctx["kit"].get("handle") or "",
                 "cta": cfg["call_to_action"] or "(none)", "language": cfg["language"], "style": cfg["style"], "scenes": cfg["scenes"],
                 "topic": f"{topic} (use exactly this topic)" if v["topic"] else (topic or "(choose one)"),
                 "ideas": "(not needed: the topic is given)" if v["topic"] else ("; ".join(ideas[:10]) or "(none: use the services)"),
                 "recent": "; ".join(ctx["recent"][:15]) or "(none)",
                 "feedback": feedback}
        mock = _mock_plan(topic or (ctx["services"].split(",")[0] if ctx["services"] != "(not listed)" else "A day at work"), cfg["scenes"], ctx["business"],
                          cfg["call_to_action"])
        try:
            res = await complete(prompt.tier, prompt.render(**vars_), org_id=org_id, prompt_key=prompt.key, prompt_version=prompt.version,
                                 json_output=True, mock_response=json.dumps(mock), temperature=0.7, prefer=cfg["planner"])
            plan = res.data if isinstance(res.data, dict) else {}
            problems = rule_problems(plan, cfg["scenes"])
            if not problems:
                c = await complete(check.tier, check.render(business=ctx["business"], about=ctx["about"], services=ctx["services"], plan=json.dumps(plan, ensure_ascii=False)),
                                   org_id=org_id, prompt_key=check.key, prompt_version=check.version, json_output=True,
                                   mock_response=json.dumps({"ok": True, "problems": []}), temperature=0, prefer=cfg["planner"])
                verdict = c.data if isinstance(c.data, dict) else {"ok": True, "problems": []}
                problems = [] if verdict.get("ok") else [str(p) for p in verdict.get("problems") or ["the reviewer flagged it"]]
        except AllModelsFailed:
            problems = ["the writing models are busy: try again in a few minutes"]
        if not problems:
            break
        feedback = "Your previous plan had these problems; fix them:\n- " + "\n- ".join(problems)
    tags = [t if t.startswith("#") else f"#{t}" for t in plan.get("hashtags") or []][:6]
    if plan:
        plan["hashtags"] = (["#Shorts"] + [t for t in tags if t.lower() != "#shorts"])[:6]
    checks = [{"ok": not problems, "problems": problems, "at": datetime.now(UTC).isoformat()}]
    if problems:
        await _set(org_id, vid, status="needs_attention", plan=plan, checks=checks, topic=(plan.get("topic") or topic or "")[:200] or None,
                   error="; ".join(problems)[:500])
        async with tenant_session(org_id) as conn:
            await _card(conn, org_id, vid, f"A video plan needs a look: {plan.get('title') or topic or 'untitled'}",
                        "Problems: " + "; ".join(problems) + ". Edit the plan and generate it, or reject it.")
        return {"status": "needs_attention", "problems": problems}
    await _set(org_id, vid, status="generating", plan=plan, checks=checks, topic=(plan.get("topic") or topic or "")[:200] or None,
               model=gen.model_name(cfg["provider"], cfg["quality"]), cost_usd=0 if gen.test_mode(cfg["provider"]) else cost, seconds=cfg["scenes"] * SCENE_S)
    return {"status": "generating"}


# ---------- generate, compose ----------

async def start_scenes(org_id: str, vid: str) -> list[dict]:
    async with tenant_session(org_id) as conn:
        _s, cfg = await settings_of(conn)
        v = (await conn.execute(text("select plan, ops from app.ai_videos where id = cast(:i as uuid)"), {"i": vid})).mappings().one()
    ops = list(v["ops"] or [])
    style = cfg["style"]
    for i, s in enumerate(v["plan"]["scenes"]):
        if i < len(ops) and ops[i].get("name"):
            continue  # started before a restart
        name = await gen.start(cfg["provider"], f"{s['prompt']} Style: {style}. Vertical 9:16 framing.", quality=cfg["quality"], aspect="9:16", seconds=SCENE_S)
        ops = [*ops[:i], {"name": name, "status": "running"}, *ops[i + 1:]]
        await _set(org_id, vid, ops=ops)
    return ops


async def poll_scenes(org_id: str, vid: str) -> dict:
    async with tenant_session(org_id) as conn:
        ops = list((await conn.execute(text("select ops from app.ai_videos where id = cast(:i as uuid)"), {"i": vid})).scalar_one() or [])
    for o in ops:
        if o["status"] == "running":
            r = await gen.poll(o["name"])
            if r["done"]:
                o.update(status="failed" if r["error"] else "done", uri=r["uri"], error=r["error"])
    await _set(org_id, vid, ops=ops)
    return {"done": all(o["status"] != "running" for o in ops), "failed": [o.get("error") for o in ops if o["status"] == "failed"]}


async def compose(org_id: str, vid: str) -> dict:
    async with tenant_session(org_id) as conn:
        v = (await conn.execute(text("select plan, ops from app.ai_videos where id = cast(:i as uuid)"), {"i": vid})).mappings().one()
        kit = await brand.get_kit(conn, org_id)
        business = (await conn.execute(text("select name from auth.organization where id = :o"), {"o": org_id})).scalar_one_or_none() or ""
    out_dir = folder(org_id, vid)
    scenes = []
    for i, (o, s) in enumerate(zip(v["ops"], v["plan"]["scenes"], strict=False)):
        p = out_dir / f"scene-{i + 1}.mp4"
        if not p.exists():
            await gen.download(o["uri"], p, caption=s.get("caption") or "", kit=kit, seconds=SCENE_S)
        scenes.append(p)
    out = out_dir / "video.mp4"
    length = await render(scenes, out, v["plan"], kit, business, brand.logo_path(kit))
    rel = str(out.resolve().relative_to(Path(settings.content_dir).resolve()))
    await _set(org_id, vid, path=rel, seconds=length, status="composing")
    return {"path": rel, "seconds": length}


async def render(scenes: list[Path], out: Path, plan: dict, kit: dict, business: str, logo: Path | None) -> float:
    """Scenes joined at 1080x1920 30 fps, hook banner for 3 s, a caption per scene, the brand end card for 2 s."""
    W, H = clips.W, clips.H
    durs = []
    with tempfile.TemporaryDirectory() as tmp:
        t = Path(tmp)
        inputs: list[str] = []
        chain: list[str] = []
        for i, p in enumerate(scenes):
            info = await clips.probe(p)
            durs.append(min(info["duration"] or SCENE_S, SCENE_S + 0.5))
            inputs += ["-i", str(p)]
            chain.append(f"[{i}:v]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},setsar=1,fps=30,trim=0:{durs[-1]},setpts=PTS-STARTPTS[v{i}]")
            if info["audio"]:
                chain.append(f"[{i}:a]aresample=48000,aformat=channel_layouts=stereo,atrim=0:{durs[-1]},asetpts=PTS-STARTPTS[a{i}]")
            else:
                chain.append(f"anullsrc=r=48000:cl=stereo,atrim=0:{durs[-1]}[a{i}]")
        n = len(scenes)
        chain.append("".join(f"[v{i}][a{i}]" for i in range(n)) + f"concat=n={n}:v=1:a=1[vc][ac]")
        total = round(sum(durs), 2)
        chain.append(f"[vc]tpad=stop_mode=clone:stop_duration={clips.OUTRO_S}[b0]")
        overlays: list[tuple[str, str]] = []

        def add(png: bytes, where: str) -> None:
            f = t / f"o{len(overlays)}.png"
            f.write_bytes(png)
            overlays.append((str(f), where))
        if plan.get("hook"):
            add(clips.hook_png(plan["hook"], kit), f"x=0:y=0:enable='lt(t,{clips.HOOK_S})'")
        start = 0.0
        for i, s in enumerate(plan.get("scenes") or []):
            if i < n and s.get("caption"):
                add(clips.caption_png(s["caption"], kit), f"x=0:y={H - 620}:enable='between(t,{start + 0.3:.2f},{start + durs[i] - 0.2:.2f})'")
            start += durs[i] if i < n else 0
        add(clips.end_card_png(kit, business, logo), f"x=0:y=0:enable='gte(t,{total})'")
        for f, _ in overlays:
            inputs += ["-i", f]
        for k, (_, where) in enumerate(overlays, 1):
            chain.append(f"[b{k - 1}][{n + k - 1}:v]overlay={where}[b{k}]")
        chain.append(f"[ac]apad=whole_dur={total + clips.OUTRO_S}[aout]")
        cmd = ["ffmpeg", "-nostdin", "-y", *inputs, "-filter_complex", ";".join(chain), "-map", f"[b{len(overlays)}]", "-map", "[aout]",
               "-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "128k",
               "-movflags", "+faststart", "-t", f"{total + clips.OUTRO_S}", str(out)]
        await clips._exec(*cmd)
    return round(total + clips.OUTRO_S, 2)


# ---------- review and publish ----------

async def ready(org_id: str, vid: str) -> str:
    """After composing: a review card (approval mode, or no YouTube yet) or straight to publishing (live)."""
    from agentry.connectors.store import get_connection
    async with tenant_session(org_id) as conn:
        status, _cfg = await settings_of(conn)
        v = (await conn.execute(text("select plan, seconds, cost_usd, model from app.ai_videos where id = cast(:i as uuid)"), {"i": vid})).mappings().one()
        await emit(conn, org_id, "video.generated", {"video_id": vid, "seconds": float(v["seconds"] or 0), "mock": v["model"] == "test"})
        yt = await get_connection(org_id, "youtube")
        if status == "live" and yt:
            await conn.execute(text("update app.ai_videos set status = 'publishing' where id = cast(:i as uuid)"), {"i": vid})
            return "publish"
        await conn.execute(text("update app.ai_videos set status = 'review' where id = cast(:i as uuid)"), {"i": vid})
        await _card(conn, org_id, vid, f"New video to approve: {v['plan'].get('title')}",
                    (v["plan"].get("description") or "") + ("" if yt else "\n\nConnect YouTube in Settings → Connections to publish it."))
    return "review"


async def publish(org_id: str, vid: str) -> dict:
    from agentry.connectors.store import get_connection
    from agentry.connectors.youtube import YouTube, YouTubeError
    async with tenant_session(org_id) as conn:
        _s, cfg = await settings_of(conn)
        v = (await conn.execute(text("select plan, path, publish, status from app.ai_videos where id = cast(:i as uuid)"), {"i": vid})).mappings().one()
    if v["status"] == "published":
        return dict(v["publish"])
    yt = await get_connection(org_id, "youtube")
    if not yt:
        await _set(org_id, vid, status="review", error="YouTube isn't connected: connect it in Settings → Connections, then approve again")
        return {"error": "youtube not connected"}
    path = resolve(v["path"])
    if not path:
        await _set(org_id, vid, status="failed", error="the video file is missing")
        return {"error": "file missing"}
    plan = v["plan"]
    desc = (plan.get("description") or "") + "\n\n" + " ".join(plan.get("hashtags") or [])
    lang = {"english": "en", "hindi": "hi", "hinglish": "hi"}.get(cfg["language"].strip().lower())
    try:
        r = await YouTube(org_id, yt).upload(path.read_bytes(), title=plan.get("title") or "Video", description=desc.strip(),
                                             tags=[h.lstrip("#") for h in plan.get("hashtags") or []], privacy=cfg["privacy"], language=lang)
    except YouTubeError as e:
        await _set(org_id, vid, status="review", error=f"publishing failed: {e}")
        return {"error": str(e)}
    pub = {"platform": "youtube", "id": r["id"], "url": r["url"], "privacy": r["privacy"], "at": datetime.now(UTC).isoformat()}
    await _set(org_id, vid, status="published", publish=pub, error=None)
    async with tenant_session(org_id) as conn:
        await emit(conn, org_id, "video.published", {"video_id": vid, "platform": "youtube", "url": r["url"]})
    return pub


# ---------- the workflow ----------

@DBOS.step()
async def video_plan_step(org_id: str, vid: str) -> dict:
    return await plan_video(org_id, vid)


@DBOS.step(retries_allowed=True, max_attempts=3, interval_seconds=20)
async def video_start_step(org_id: str, vid: str) -> int:
    return len(await start_scenes(org_id, vid))


@DBOS.step(retries_allowed=True, max_attempts=3, interval_seconds=10)
async def video_poll_step(org_id: str, vid: str) -> dict:
    return await poll_scenes(org_id, vid)


@DBOS.step(retries_allowed=True, max_attempts=2, interval_seconds=20)
async def video_compose_step(org_id: str, vid: str) -> dict:
    return await compose(org_id, vid)


@DBOS.step()
async def video_ready_step(org_id: str, vid: str) -> str:
    return await ready(org_id, vid)


@DBOS.step()
async def video_publish_step(org_id: str, vid: str) -> dict:
    return await publish(org_id, vid)


@DBOS.step()
async def video_fail_step(org_id: str, vid: str, error: str) -> None:
    await _set(org_id, vid, status="failed", error=error[:500], cost_usd=0)


def _reason(e: Exception) -> str:
    """The real error behind a step that ran out of retries (DBOS wraps it)."""
    for x in (e, *(getattr(e, "errors", None) or [])):
        if isinstance(x, (veo.VeoError, clips.ClipError)):
            return str(x)
    inner = getattr(e, "errors", None)
    return str(inner[-1]) if inner else str(e)


async def generate_and_finish(org_id: str, vid: str) -> str:
    try:
        await video_start_step(org_id, vid)
    except Exception as e:  # noqa: BLE001 - after its retries a step's last error is wrapped; the video must not stay "generating"
        await video_fail_step(org_id, vid, _reason(e))
        return "failed"
    for _ in range(POLL_MAX):
        try:
            r = await video_poll_step(org_id, vid)
        except Exception as e:  # noqa: BLE001
            await video_fail_step(org_id, vid, _reason(e))
            return "failed"
        if r["done"]:
            break
        await DBOS.sleep_async(POLL_S)
    else:
        await video_fail_step(org_id, vid, "the video model took longer than 12 minutes")
        return "failed"
    if r["failed"]:
        await video_fail_step(org_id, vid, "; ".join(e or "a scene failed" for e in r["failed"]))
        return "failed"
    try:
        await video_compose_step(org_id, vid)
    except Exception as e:  # noqa: BLE001
        await video_fail_step(org_id, vid, _reason(e))
        return "failed"
    if await video_ready_step(org_id, vid) == "publish":
        await video_publish_step(org_id, vid)
        return "published"
    return "review"


@on("video.requested")
@DBOS.workflow()
async def make_video(event: dict) -> None:
    org_id, vid = event["org_id"], event["payload"]["video_id"]
    if (await video_plan_step(org_id, vid))["status"] == "generating":
        await generate_and_finish(org_id, vid)


@on("video.plan_approved")
@DBOS.workflow()
async def make_video_from_plan(event: dict) -> None:
    """A person fixed or accepted a plan that needed attention: generate it as it is now."""
    await generate_and_finish(event["org_id"], event["payload"]["video_id"])


@on("approval.decided")
@DBOS.workflow()
async def video_card_decided(event: dict) -> None:
    p = event["payload"]
    if p.get("kind") == "video_review" and p.get("status") in ("approved", "edited", "rejected"):
        await video_card_step(event["org_id"], p["approval_id"], p["status"])


@DBOS.step()
async def video_card_step(org_id: str, approval_id: str, status: str) -> str:
    async with tenant_session(org_id) as conn:
        vid = (await conn.execute(text("select payload->>'video_id' from app.approvals where id = cast(:a as uuid)"), {"a": approval_id})).scalar_one()
        st = (await conn.execute(text("select status from app.ai_videos where id = cast(:i as uuid)"), {"i": vid})).scalar_one_or_none()
    if st != "review":
        return st or "gone"
    if status == "rejected":
        await _set(org_id, vid, status="rejected")
        return "rejected"
    await _set(org_id, vid, status="publishing")
    return (await publish(org_id, vid)).get("url") or "review"


# ---------- schedule ----------

def due_slot(cfg: dict, tz: str, now: datetime) -> str | None:
    """The slot (local "YYYY-MM-DD HH:MM") to make a video for, if it's a scheduled day and the time has come (within 3 hours)."""
    local = now.astimezone(ZoneInfo(tz or "Asia/Kolkata"))
    if DAYS[local.weekday()] not in cfg["days"]:
        return None
    hh, mm = (int(x) for x in cfg["time"].split(":"))
    at = local.replace(hour=hh, minute=mm, second=0, microsecond=0)
    return f"{at:%Y-%m-%d %H:%M}" if at <= local < at + timedelta(hours=3) else None


async def schedule(now: datetime | None = None) -> int:
    now = now or datetime.now(UTC)
    async with system_session() as conn:
        rows = (await conn.execute(text("""select a.org_id, a.config, s.timezone from app.automation_instances a join app.org_settings s on s.org_id = a.org_id
            where a.template_key = 'video_studio' and a.status in ('live','approval_mode')"""))).mappings().all()
    made = 0
    for r in rows:
        cfg = VideoConfig(**(r["config"] or {})).model_dump()
        slot = due_slot(cfg, r["timezone"], now)
        if slot:
            async with tenant_session(r["org_id"]) as conn:
                made += bool(await request(conn, r["org_id"], topic=None, trigger="schedule", slot=slot))
    return made


@DBOS.step()
async def video_schedule_step() -> int:
    return await schedule()


@DBOS.workflow()
async def video_schedule(scheduled_time: datetime, context) -> None:
    await video_schedule_step()


def available() -> bool:
    return bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))

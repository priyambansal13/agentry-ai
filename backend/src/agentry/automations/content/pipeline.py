"""One durable workflow per upload (Phase 6.1-6.3): transcribe -> find the best moments -> for each moment, a post per
platform with its quote card. Each moment is its own step, so a crash or a model outage resumes where it stopped.
The source's status and progress drive the portal page while it works."""
import json
from datetime import UTC, datetime

from dbos import DBOS, SetWorkflowID
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from agentry.automations.content import brand, drafts, moments, sources
from agentry.db import tenant_session
from agentry.events import emit
from agentry.runs import current, run

CONTEXT_SECONDS = 60


async def _status(conn: AsyncConnection, sid: str, status: str, **progress: object) -> None:
    await conn.execute(text("""update app.content_sources set status = :s, progress = progress || cast(:p as jsonb)
        where id = cast(:i as uuid)"""), {"s": status, "p": json.dumps(progress), "i": sid})


def context_around(transcript: dict, start: float, end: float) -> str:
    return " ".join(s["text"] for s in transcript["segments"] if s["end"] >= start - CONTEXT_SECONDS and s["start"] <= end + CONTEXT_SECONDS)


@DBOS.step()
async def content_transcribe(org_id: str, sid: str) -> None:
    async with tenant_session(org_id) as conn:
        s = (await conn.execute(text("select kind, file_path, transcript from app.content_sources where id = cast(:i as uuid)"), {"i": sid})).mappings().one()
        if s["transcript"]:
            return  # transcript and sample sources arrive with one
        await _status(conn, sid, "transcribing")
    path = sources.resolve(s["file_path"])
    if not path:
        raise sources.TranscribeError("the uploaded file is missing")
    transcript, cost = await sources.transcribe_file(path)
    async with tenant_session(org_id) as conn:
        await conn.execute(text("update app.content_sources set transcript = cast(:t as jsonb), cost_usd = cost_usd + :c where id = cast(:i as uuid)"),
                           {"t": json.dumps(transcript), "c": cost, "i": sid})


@DBOS.step()
async def content_find_moments(org_id: str, sid: str) -> list[str]:
    async with tenant_session(org_id) as conn:
        await _status(conn, sid, "finding_moments")
        s = (await conn.execute(text("select title, transcript from app.content_sources where id = cast(:i as uuid)"), {"i": sid})).mappings().one()
        kit = await brand.get_kit(conn, org_id)
    top = moments.rank(await moments.mine(org_id, s["title"], s["transcript"]), kit["moments_per_source"])
    async with tenant_session(org_id) as conn:
        await conn.execute(text("delete from app.content_moments where source_id = cast(:i as uuid)"), {"i": sid})
        ids = []
        for rank, m in enumerate(top, 1):
            ids.append(str((await conn.execute(text("""insert into app.content_moments (org_id, source_id, rank, start_s, end_s, quote, speaker,
                hook, insight, topic, score) values (:o, cast(:s as uuid), :r, :a, :b, :q, :sp, :h, :ins, :t, :sc) returning id"""),
                {"o": org_id, "s": sid, "r": rank, "a": m["start"], "b": m["end"], "q": m["quote"], "sp": m["speaker"], "h": m["hook"],
                 "ins": m["insight"], "t": m["topic"], "sc": m["score"]})).scalar_one()))
        await _status(conn, sid, "writing", moments_total=len(ids), moments_done=0)
    return ids


async def write_one(conn: AsyncConnection, org_id: str, moment_id: str, platform: str, kit: dict, transcript: dict) -> dict:
    """Draft (or redraft) one post and draw its card."""
    m = dict((await conn.execute(text("select * from app.content_moments where id = cast(:i as uuid)"), {"i": moment_id})).mappings().one())
    mom = {"quote": m["quote"], "speaker": m["speaker"], "hook": m["hook"], "insight": m["insight"]}
    d = await drafts.draft_post(org_id, platform, mom, context_around(transcript, float(m["start_s"]), float(m["end_s"])),
                                sources.full_text(transcript), kit.get("voice"))
    post = (await conn.execute(text("""insert into app.content_posts (org_id, source_id, moment_id, platform, body, hashtags, critic, review)
        values (:o, :s, cast(:m as uuid), :p, :b, :h, cast(:c as jsonb), :r)
        on conflict (moment_id, platform) do update set body = excluded.body, hashtags = excluded.hashtags, critic = excluded.critic,
          review = excluded.review, edited = false, reviewed_by = null, reviewed_at = null, updated_at = now()
        returning id, source_id, platform"""),
        {"o": org_id, "s": m["source_id"], "m": moment_id, "p": platform, "b": d["body"], "h": d["hashtags"],
         "c": json.dumps({k: d[k] for k in ("ok", "problems", "attempts")}), "r": "pending" if d["ok"] else "needs_attention"})).mappings().one()
    await brand.render_post_image(conn, org_id, kit, dict(post), mom)
    return {"id": str(post["id"]), **d}


@DBOS.step()
async def content_write_moment(org_id: str, sid: str, moment_id: str) -> int:
    async with tenant_session(org_id) as conn:
        kit = await brand.get_kit(conn, org_id)
        cfg = (await conn.execute(text("select config from app.automation_instances where template_key = 'content_repurposing'"))).scalar_one_or_none() or {}
        if cfg.get("call_to_action"):
            kit["voice"] = f"{kit.get('voice') or ''}\nCall to action, only where it fits naturally: {cfg['call_to_action']}".strip()
        transcript = (await conn.execute(text("select transcript from app.content_sources where id = cast(:i as uuid)"), {"i": sid})).scalar_one()
        for platform in kit["platforms"]:
            await write_one(conn, org_id, moment_id, platform, kit, transcript)
        await conn.execute(text("""update app.content_sources set progress = jsonb_set(progress, '{moments_done}',
            to_jsonb(coalesce((progress->>'moments_done')::int, 0) + 1)) where id = cast(:i as uuid)"""), {"i": sid})
    return len(kit["platforms"])


@DBOS.step()
async def content_finish(org_id: str, sid: str, error: str | None = None) -> None:
    async with tenant_session(org_id) as conn:
        if error:
            await conn.execute(text("update app.content_sources set status = 'failed', error = :e where id = cast(:i as uuid)"), {"e": error[:300], "i": sid})
        else:
            await conn.execute(text("update app.content_sources set status = 'ready', error = null, ready_at = :t where id = cast(:i as uuid)"),
                               {"t": datetime.now(UTC), "i": sid})
        await emit(conn, org_id, "content.ready" if not error else "content.failed", {"source_id": sid})


@DBOS.workflow()
async def content_process_source(org_id: str, sid: str) -> str:
    async with run(org_id, "content_repurposing", "content.source", key=f"content:{sid}", subject=("content_source", sid)) as r:
        result = await _content_process_source(org_id, sid)
        if result == "failed":
            r.fail("stopped part-way: see the recording's page")
        return result


async def _content_process_source(org_id: str, sid: str) -> str:
    try:
        await content_transcribe(org_id, sid)
        mids = await content_find_moments(org_id, sid)
        current().step("moments found", moments=len(mids))
        for mid in mids:
            await content_write_moment(org_id, sid, mid)
        current().step("posts written")
    except Exception as e:  # noqa: BLE001 - shown on the source with a retry button; finished moments are kept
        await content_finish(org_id, sid, str(e))
        return "failed"
    await content_finish(org_id, sid)
    return "ready"


async def start(org_id: str, sid: str, attempt: int = 0) -> None:
    with SetWorkflowID(f"content-{sid}-{attempt}"):
        await DBOS.start_workflow_async(content_process_source, org_id, sid)

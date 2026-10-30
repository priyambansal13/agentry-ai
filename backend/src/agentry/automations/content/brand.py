"""The brand kit (Phase 6.3): colours, card template, logo, handle, platforms, and the brand voice learned from the
client's own past posts (pasted in), so drafts sound like them. Only the voice guide is kept, not the posts."""
import re
import statistics
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from agentry.automations.content import images, sources
from agentry.llm.gateway import AllModelsFailed, complete

VOICE_PROMPT = """Below are social media posts one business wrote. Describe HOW they write, as 5 to 7 short instructions another
writer can follow: tone, sentence length, how posts open and end, emoji and hashtag habits, words they like, words they avoid.
Style only: no topics, names, prices or claims.

{posts}"""
EMOJI = re.compile("[\U0001F300-\U0001FAFF☀-➿]")


async def get_kit(conn: AsyncConnection, org_id: str) -> dict:
    kit = (await conn.execute(text("select * from app.brand_kits"))).mappings().first()
    if not kit:
        await conn.execute(text("insert into app.brand_kits (org_id) values (:o) on conflict do nothing"), {"o": org_id})
        kit = (await conn.execute(text("select * from app.brand_kits"))).mappings().one()
    return dict(kit)


def split_posts(raw: str) -> list[str]:
    """Posts pasted one after another, separated by a blank line or a line of dashes."""
    parts = [p.strip() for p in re.split(r"\n\s*(?:-{3,}|={3,})\s*\n|\n\s*\n\s*\n", raw) if p.strip()]
    if len(parts) < 3:
        parts = [p.strip() for p in re.split(r"\n\s*\n", raw) if len(p.strip()) > 40]
    return [p for p in parts if len(p) >= 30][:40]


def heuristic_voice(posts: list[str]) -> str:
    words = statistics.median(len(p.split()) for p in posts)
    emoji = sum(bool(EMOJI.search(p)) for p in posts) / len(posts)
    tags = statistics.median(len(re.findall(r"#\w+", p)) for p in posts)
    questions = sum(p.rstrip().endswith("?") for p in posts) / len(posts)
    first_person = sum(bool(re.search(r"\b(I|I'm|I've|my)\b", p)) for p in posts) / len(posts)
    out = [f"- Posts are about {int(words)} words long.",
           "- Writes in the first person (I, my)." if first_person > 0.5 else "- Writes as the business (we, our).",
           "- Uses emoji now and then." if emoji > 0.3 else "- Rarely uses emoji.",
           f"- Uses about {int(tags)} hashtags per post." if tags else "- Hardly uses hashtags.",
           "- Often ends with a question to the reader." if questions > 0.3 else "- Ends with a statement, not a question.",
           "- Plain, direct sentences; no hype."]
    return "\n".join(out)


async def learn_voice(conn: AsyncConnection, org_id: str, raw: str) -> dict:
    posts = split_posts(raw)
    if len(posts) < 3:
        return {"learned": False, "samples": len(posts), "reason": "paste at least 3 posts, separated by blank lines"}
    fallback = heuristic_voice(posts)
    try:
        res = await complete("writer", [{"role": "user", "content": VOICE_PROMPT.format(posts="\n\n---\n\n".join(p[:800] for p in posts[:25]))}],
                             org_id=org_id, prompt_key="brand_voice", prompt_version="v1", mock_response=fallback)
        voice = res.text.strip() or fallback
    except AllModelsFailed:
        voice = fallback
    await conn.execute(text("update app.brand_kits set voice = :v, voice_samples = :n, updated_at = now()"), {"v": voice[:2000], "n": len(posts)})
    return {"learned": True, "samples": len(posts), "voice": voice}


def logo_path(kit: dict) -> Path | None:
    return sources.resolve(kit.get("logo_path"))


async def render_post_image(conn: AsyncConnection, org_id: str, kit: dict, post: dict, moment: dict) -> str:
    """Draw (or redraw) a post's card and store it; returns its relative path."""
    png = images.render(post["platform"], moment["quote"], moment.get("speaker"), kit, logo_path(kit))
    path = sources.folder(org_id, str(post["source_id"])) / f"{post['id']}.png"
    path.write_bytes(png)
    rel = sources.relative(path)
    await conn.execute(text("update app.content_posts set image_path = :p, updated_at = now() where id = cast(:i as uuid)"),
                       {"p": rel, "i": str(post["id"])})
    return rel


async def rerender_all(conn: AsyncConnection, org_id: str) -> int:
    """After the brand kit changes: every card not yet published is redrawn."""
    kit = await get_kit(conn, org_id)
    rows = (await conn.execute(text("""select p.id, p.source_id, p.platform, m.quote, m.speaker from app.content_posts p
        join app.content_moments m on m.id = p.moment_id where p.published_at is null and p.review <> 'dropped'"""))).mappings().all()
    for r in rows:
        await render_post_image(conn, org_id, kit, dict(r), {"quote": r["quote"], "speaker": r["speaker"]})
    return len(rows)

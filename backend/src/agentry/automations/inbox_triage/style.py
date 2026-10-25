"""Writing style (#1): learned from the business's own sent emails, so drafts sound like them.

Reads up to 50 sent emails from the last 6 months (the new text only, quoted replies removed), and turns them into a
short style guide: greeting, length, formality, sign-off, phrases, language mix. Only the guide is stored (in the
business profile), never the emails. Learned when Gmail is first connected, and again on request.
"""
import re
import statistics
from collections import Counter
from datetime import UTC, datetime

from sqlalchemy import text

from agentry.connectors.gmail import Gmail, GmailError, _body
from agentry.connectors.store import get_connections
from agentry.db import tenant_session
from agentry.llm.gateway import AllModelsFailed, complete

PROMPT = """Below are emails one small-business owner wrote. Describe HOW they write, as 6 to 8 short instructions another
writer can follow: how they greet, typical length, formality and tone, how they sign off, phrases they often use, and
their language (English, Hindi, Hinglish...). Describe the style only: no names, prices, clients or other details.

{samples}"""


def new_text(body: str) -> str:
    """The part of a sent email the owner actually wrote: stop at the quoted earlier message."""
    out = []
    for line in body.splitlines():
        if re.match(r"^\s*On .+wrote:\s*$", line) or line.startswith(("-----Original Message", "From:")):
            break
        if not line.startswith(">"):
            out.append(line.rstrip())
    return "\n".join(out).strip()


def heuristic_style(samples: list[str]) -> str:
    """A plain style guide from simple counts: used without a model, and as the model's fallback."""
    firsts = Counter(re.split(r"[\s,]", s.strip().splitlines()[0])[0].capitalize() for s in samples if s.strip())
    lasts = Counter(s.strip().splitlines()[-1].strip() for s in samples if len(s.strip().splitlines()) > 1)
    words = statistics.median(len(s.split()) for s in samples) if samples else 60
    hindi = sum(bool(re.search(r"[ऀ-ॿ]", s)) for s in samples)
    greet = firsts.most_common(1)[0][0] if firsts else "Hi"
    sign = lasts.most_common(1)[0][0] if lasts else ""
    lines = [f"- Greets with \"{greet} <name>,\".", f"- Keeps emails short: about {int(words)} words.",
             "- Friendly and direct; no long pleasantries."]
    if sign and len(sign) < 40:
        lines.append(f"- Signs off with \"{sign}\".")
    if hindi:
        lines.append("- Writes some emails in Hindi (Devanagari) when the other person does.")
    return "\n".join(lines)


async def sent_samples(org_id: str, limit: int = 50) -> list[str]:
    samples: list[str] = []
    for conn in await get_connections(org_id, "gmail"):
        g = Gmail(org_id, conn)
        try:
            listed = await g.call("GET", "/messages", params={"q": "in:sent newer_than:180d", "maxResults": limit})
            for m in listed.get("messages", [])[:limit]:
                full = await g.call("GET", f"/messages/{m['id']}", params={"format": "full"})
                t = new_text(_body(full.get("payload", {})))
                if 20 <= len(t) <= 4000:
                    samples.append(t)
        except GmailError:
            continue
    return samples[:limit]


async def learn_style(org_id: str) -> dict:
    samples = await sent_samples(org_id)
    if len(samples) < 3:
        return {"learned": False, "samples": len(samples), "reason": "fewer than 3 sent emails found"}
    fallback = heuristic_style(samples)
    joined = "\n\n---\n\n".join(s[:700] for s in samples[:30])
    try:
        res = await complete("writer", [{"role": "user", "content": PROMPT.format(samples=joined)}], org_id=org_id,
                             prompt_key="writing_style", prompt_version="v1", mock_response=fallback)
        guide = res.text.strip() or fallback
    except AllModelsFailed:
        guide = fallback
    async with tenant_session(org_id) as conn:
        await conn.execute(text("""update app.org_settings set profile = profile || jsonb_build_object('writing_style', cast(:g as text),
            'writing_style_learned_at', cast(:t as text), 'writing_style_samples', cast(:n as int))"""),
            {"g": guide[:2000], "t": datetime.now(UTC).isoformat(timespec="seconds"), "n": len(samples)})
    return {"learned": True, "samples": len(samples), "style": guide}

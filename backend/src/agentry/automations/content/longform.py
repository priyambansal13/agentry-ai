"""Blog article + newsletter from one recording (ROADMAP-V2 8.3).

From the ranked moments and the transcript, the `writer` model drafts:
    blog        a 600-900 word article: title, meta description, slug, an intro, H2 sections built on the moments
                (each with an exact quote), and a short FAQ
    newsletter  subject, preheader and a 200-300 word email: three takeaways and one call to action
The same checks as the posts: anything in quotation marks must be word for word in the recording, numbers must appear
in the recording, no AI filler. A failed check gets one rewrite with the reasons; still failing -> needs_attention (a
person fixes it). Exports: Markdown and HTML (paste into WordPress, Mailchimp, Brevo).
"""
import html
import json
import re

from dbos import DBOS
from sqlalchemy import text

from agentry import runs
from agentry.automations.content.brand import get_kit
from agentry.automations.content.drafts import FILLER, QUOTED
from agentry.automations.content.moments import norm, quote_in
from agentry.db import tenant_session
from agentry.llm.gateway import AllModelsFailed, complete
from agentry.worker.handlers import on

SPEC = {
    "blog": ("an SEO blog article of 600-900 words", ('{"title": str (under 65 characters), "summary": str (meta description, under 155 characters), '
             '"slug": str (lowercase-words-with-dashes), "body": str (Markdown: a short intro, 3-5 "## " sections each built on one moment '
             'and quoting it word for word in "double quotes", then "## FAQ" with 3 questions as "### " and short answers)}')),
    "newsletter": ("an email newsletter of 200-300 words", ('{"title": str (the email subject, under 60 characters), "summary": str '
                   '(the preheader, under 90 characters), "body": str (Markdown: a one-line greeting, three short takeaways as a list, '
                   'one quote word for word in "double quotes", one call to action, a sign-off)}')),
}


def transcript_text(transcript: dict | None) -> str:
    return " ".join(s.get("text", "") for s in (transcript or {}).get("segments", []))


MIN_WORDS = {"blog": 200, "newsletter": 80}


def check(body: str, title: str, transcript: str, kind: str = "newsletter") -> list[str]:
    problems = []
    if len(body.split()) < MIN_WORDS[kind]:
        problems.append(f"too short for a {kind} (under {MIN_WORDS[kind]} words)")
    for q in QUOTED.findall(body):
        if not quote_in(q, transcript):
            problems.append(f"quote not found word for word in the recording: \"{q[:60]}\"")
    source = norm(transcript).replace(",", "")
    for n in re.findall(r"\d[\d,.]*%?", f"{title} {body}"):
        digits = n.replace(",", "").rstrip(".%")
        if len(digits) > 1 and not re.search(rf"(?<![\d.]){re.escape(digits)}(?![\d])", source):
            problems.append(f"the number {n} isn't in the recording")
    if m := FILLER.search(f"{title} {body}"):
        problems.append(f"sounds like AI filler: \"{m.group(0)}\"")
    return problems


def slugify(s: str) -> str:
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", s.lower())).strip("-")[:80] or "article"


def template(kind: str, title: str, moments: list[dict], business: str) -> dict:
    """The no-model draft: the moments' hooks, insights and exact quotes, assembled."""
    if kind == "blog":
        parts = [f"In this conversation, {business} shares what has worked in practice. Here are the key ideas, in their own words."]
        for m in moments[:4]:
            parts += [f"## {m['hook']}", m["insight"], f"> \"{m['quote']}\"" + (f" ({m['speaker']})" if m.get("speaker") else "")]
        parts += ["## FAQ"] + [f"### {m['hook']}?\n{m['insight']}" for m in moments[:3]]
        return {"title": title[:65], "summary": (moments[0]["insight"] if moments else title)[:155], "slug": slugify(title), "body": "\n\n".join(parts)}
    takeaways = "\n".join(f"- **{m['hook']}**: {m['insight']}" for m in moments[:3])
    quote = f"\n\n\"{moments[0]['quote']}\"" if moments else ""
    return {"title": f"3 ideas from {title}"[:60], "summary": (moments[0]["hook"] if moments else title)[:90],
            "body": f"Hi there,\n\nThree things worth taking from our latest conversation:\n\n{takeaways}{quote}\n\nReply to this email if you'd like to talk.\n\n{business}"}


async def write(org_id: str, sid: str, kind: str) -> dict:
    """Draft, check, rewrite once if needed, store. Returns the stored row's status and problems."""
    async with runs.run(org_id, "content_repurposing", f"longform_{kind}", key=f"longform:{sid}:{kind}", subject=("content_source", sid)) as r:
        async with tenant_session(org_id) as conn:
            src = (await conn.execute(text("select title, transcript from app.content_sources where id = cast(:i as uuid)"), {"i": sid})).mappings().one()
            moments = [dict(m) for m in (await conn.execute(text("""select hook, insight, quote, speaker, topic from app.content_moments
                where source_id = cast(:i as uuid) and not dropped order by rank limit 6"""), {"i": sid})).mappings().all()]
            kit = await get_kit(conn, org_id)
            business = (await conn.execute(text("select name from auth.organization where id = :o"), {"o": org_id})).scalar_one_or_none() or "we"
        tx = transcript_text(src["transcript"])
        fallback = template(kind, src["title"], moments, business)
        what, shape = SPEC[kind]
        prompt = (f"Write {what} for {business} from their recording \"{src['title']}\".\n"
                  f"Brand voice: {kit.get('voice') or 'warm, plain and expert'}.\n"
                  f"Use these moments (hook, insight, exact quote):\n{json.dumps(moments, ensure_ascii=False)}\n\n"
                  "Rules: quotes must be copied word for word from the moments; no numbers, names or claims that aren't in them; "
                  "plain, specific language; no hype.\n"
                  f"Return only JSON: {shape}")
        draft, problems = fallback, []
        for attempt in range(2):
            try:
                res = await complete("writer", [{"role": "user", "content": prompt}], org_id=org_id, prompt_key=f"content_{kind}", prompt_version="v1",
                                     json_output=True, mock_response=json.dumps(fallback))
                draft = res.data if isinstance(res.data, dict) and res.data.get("body") else fallback
            except AllModelsFailed:
                draft = fallback
            problems = check(draft.get("body", ""), draft.get("title", ""), tx, kind)
            r.step("draft", attempt=attempt + 1, problems=len(problems))
            if not problems:
                break
            prompt += "\n\nYour previous draft had these problems, fix them: " + "; ".join(problems)
        status = "ready" if not problems else "needs_attention"
        async with tenant_session(org_id) as conn:
            await conn.execute(text("""update app.content_longform set status = :s, title = :t, summary = :su, slug = :sl, body = :b,
                problems = cast(:p as jsonb), error = null, updated_at = now() where source_id = cast(:i as uuid) and kind = :k"""),
                {"s": status, "t": (draft.get("title") or "")[:200], "su": (draft.get("summary") or "")[:300],
                 "sl": slugify(draft.get("slug") or draft.get("title") or "") if kind == "blog" else None, "b": draft.get("body") or "",
                 "p": json.dumps(problems), "i": sid, "k": kind})
    return {"status": status, "problems": problems}


@DBOS.step()
async def content_longform_step(org_id: str, sid: str, kind: str) -> str:
    try:
        return (await write(org_id, sid, kind))["status"]
    except Exception as e:  # noqa: BLE001 - recorded on the row; the person can try again
        async with tenant_session(org_id) as conn:
            await conn.execute(text("""update app.content_longform set status = 'failed', error = :e, updated_at = now()
                where source_id = cast(:i as uuid) and kind = :k"""), {"e": str(e)[:300], "i": sid, "k": kind})
        return "failed"


@on("content.longform_requested")
@DBOS.workflow()
async def content_write_longform(event: dict) -> None:
    for kind in event["payload"].get("kinds", ["blog", "newsletter"]):
        await content_longform_step(event["org_id"], event["payload"]["source_id"], kind)


# ---------- export ----------

def _inline(s: str) -> str:
    s = html.escape(s)
    s = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", s)
    return re.sub(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)", r"<em>\1</em>", s)


def to_html(title: str, summary: str | None, body: str, kind: str) -> str:
    """Markdown (headings, lists, quotes, bold, italics, paragraphs) to clean HTML for a CMS or an email tool."""
    out, items = [], []

    def flush() -> None:
        if items:
            out.append("<ul>" + "".join(f"<li>{_inline(i)}</li>" for i in items) + "</ul>")
            items.clear()
    for block in re.split(r"\n\s*\n", body.strip()):
        for line in block.splitlines():
            line = line.rstrip()
            if line.startswith(("- ", "* ")):
                items.append(line[2:])
                continue
            flush()
            if m := re.match(r"^(#{1,3})\s+(.*)", line):
                level = len(m[1]) + 1  # # -> h2 (the title is the h1)
                out.append(f"<h{level}>{_inline(m[2])}</h{level}>")
            elif line.startswith(">"):
                out.append(f"<blockquote>{_inline(line.lstrip('> '))}</blockquote>")
            elif line:
                out.append(f"<p>{_inline(line)}</p>")
        flush()
    head = f"<h1>{html.escape(title)}</h1>" if kind == "blog" else ""
    meta = f'<meta name="description" content="{html.escape(summary or "")}">\n' if kind == "blog" else ""
    return f"{meta}{head}\n" + "\n".join(out) + "\n"

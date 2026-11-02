"""Hiring assistant (ROADMAP-V3 A5): CVs scored against the job with reasons, a shortlist, interviews, polite regrets.

    jobs        a title, a description and the must-haves; a job post written for Naukri / LinkedIn / Indeed to copy; a
                public apply link (a simple form on Agentry's API) to share anywhere
    candidates  CVs (PDF, Word, text) uploaded by the team or sent through the apply link; each read and scored 0-100
                against the job: strengths that quote the CV word for word (a strength without its quote is dropped),
                gaps against the must-haves, three interview questions. Never judged on name, gender, age, religion,
                caste, photo or address
    shortlist   strong fits make a Needs-you card for the owner
    interview   a time is set -> the candidate gets the details on WhatsApp / email; rejected -> a polite regret
                (settings), never automatic for the first look
"""
import json
import re
import secrets
import uuid
from datetime import datetime
from pathlib import Path

from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from agentry import audit
from agentry.automations import AutomationTemplate, register
from agentry.config import settings
from agentry.db import tenant_session
from agentry.events import emit
from agentry.knowledge import UnreadableFile, extract_text
from agentry.llm.gateway import AllModelsFailed, complete
from agentry.llm.prompts import load


class HiringConfig(BaseModel):
    shortlist_cards: bool = Field(True, title="A card when a strong candidate applies", json_schema_extra={"editable_by": "client"})
    send_regrets: bool = Field(True, title="Send a polite regret when a candidate is rejected", json_schema_extra={"editable_by": "client"})
    interview_place: str = Field("our office", title="Where interviews happen (or 'a video call')", json_schema_extra={"editable_by": "client"})


register(AutomationTemplate(
    key="hiring", name="Hiring assistant",
    description="Reads CVs, scores them against the job with reasons quoted from the CV, shortlists, books interviews and sends regrets.",
    config_model=HiringConfig, metrics=("candidates_screened",),
))

SKIP = re.compile(r"\b(male|female|married|unmarried|single|religion|caste|hindu|muslim|christian|sikh|date of birth|d\.o\.b|age\s*[:\-]?\s*\d+)\b",
                  re.IGNORECASE)


def folder(org_id: str) -> Path:
    p = Path(settings.documents_dir) / org_id / "hiring"
    p.mkdir(parents=True, exist_ok=True)
    return p


async def settings_of(conn: AsyncConnection) -> tuple[str | None, dict]:
    row = (await conn.execute(text("select status, config from app.automation_instances where template_key = 'hiring'"))).first()
    return (row.status, HiringConfig(**(row.config or {})).model_dump()) if row else (None, HiringConfig().model_dump())


async def create_job(conn: AsyncConnection, org_id: str, *, title: str, description: str, must_have: list[str], location: str | None, kind: str,
                     user_id: str | None) -> str:
    return str((await conn.execute(text("""insert into app.jobs (org_id, token, title, description, must_have, location, kind, created_by)
        values (:o, :t, :ti, :d, cast(:m as jsonb), :l, :k, :u) returning id"""),
        {"o": org_id, "t": secrets.token_urlsafe(16), "ti": title, "d": description, "m": json.dumps([m.strip() for m in must_have if m.strip()][:12]),
         "l": location, "k": kind, "u": user_id})).scalar_one())


async def write_post(org_id: str, job: dict, business: str) -> str:
    """A job post for the boards: plain, specific, no inflated claims."""
    mock = (f"{job['title']} at {business}{(' (' + job['location'] + ')') if job.get('location') else ''}\n\n{job['description']}\n\n"
            "What you'll need:\n" + "\n".join(f"- {m}" for m in job["must_have"]) + "\n\nApply with your CV.")
    msgs = [{"role": "system", "content": "You write clear, honest job posts for small Indian businesses. Plain text, 120-220 words: a one-line "
             "summary, what the work is, what's needed (the must-haves as a list), where, and how to apply. No salary unless given, no buzzwords, "
             "no claims about the business that aren't given."},
            {"role": "user", "content": f"Business: {business}\nRole: {job['title']}\nLocation: {job.get('location') or 'not given'}\n"
             f"Type: {job['kind'].replace('_', ' ')}\nDescription: {job['description']}\nMust have: {'; '.join(job['must_have'])}"}]
    try:
        r = await complete("writer", msgs, org_id=org_id, prompt_key="hiring_post", prompt_version="v1", mock_response=mock, temperature=0.4)
        return r.text.strip() or mock
    except AllModelsFailed:
        return mock


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip().lower()


def heuristic(job: dict, cv: str) -> dict:
    """Without a model (and as the test mock): must-haves found in the CV, quoted."""
    low = _norm(cv)
    strengths, gaps = [], []
    for m in job["must_have"]:
        words = [w for w in re.findall(r"[a-z0-9+#.]+", m.lower()) if len(w) > 2]
        hit = next((w for w in words if w in low), None)
        if hit:
            line = next((ln.strip() for ln in cv.splitlines() if hit in ln.lower()), hit)
            strengths.append({"point": m, "quote": line[:150]})
        else:
            gaps.append({"point": m})
    total = max(1, len(job["must_have"]))
    score = round(100 * len(strengths) / total)
    email = re.search(r"[\w.+-]+@[\w-]+\.[\w.]+", cv)
    phone = re.search(r"(\+?91[\s-]?)?[6-9]\d{4}[\s-]?\d{5}", cv)
    name = next((ln.strip() for ln in cv.splitlines() if ln.strip() and len(ln.split()) <= 4 and "@" not in ln and not re.search(r"\d", ln)), None)
    return {"name": name, "email": email.group(0) if email else None, "phone": phone.group(0) if phone else None, "score": score,
            "verdict": "strong" if not gaps else "maybe" if score >= 50 else "no", "summary": f"Shows {len(strengths)} of {total} must-haves.",
            "strengths": strengths, "gaps": gaps, "questions": [f"Tell us about your experience with {g['point']}." for g in gaps][:3] or
            ["Walk us through a recent piece of work you're proud of."]}


def checked(a: dict, cv: str, job: dict) -> dict:
    """Keep strengths whose quote is in the CV; recompute the verdict rule (strong only with every must-have shown)."""
    low = _norm(cv)
    a["strengths"] = [s for s in a.get("strengths") or [] if isinstance(s, dict) and s.get("quote") and _norm(s["quote"]) in low
                      and not SKIP.search(s.get("point", ""))]
    a["gaps"] = [g for g in a.get("gaps") or [] if isinstance(g, dict) and g.get("point")]
    try:
        a["score"] = max(0, min(100, int(a.get("score") or 0)))
    except (TypeError, ValueError):
        a["score"] = 0
    if a.get("verdict") not in ("strong", "maybe", "no"):
        a["verdict"] = "maybe"
    must_missing = [g for g in a["gaps"] if any(_norm(m)[:20] in _norm(g["point"]) or _norm(g["point"])[:20] in _norm(m) for m in job["must_have"])]
    if a["verdict"] == "strong" and must_missing:
        a["verdict"] = "maybe"
    a["questions"] = [str(q) for q in a.get("questions") or []][:3]
    return a


async def score(org_id: str, job: dict, cv: str) -> dict:
    prompt = load("hiring_score")
    clean = SKIP.sub("[removed]", cv)[:12000]  # details that must not influence the score aren't even shown
    try:
        r = await complete(prompt.tier, prompt.render(title=job["title"], must_have="; ".join(job["must_have"]) or "(none listed)",
                                                      description=job["description"][:3000], cv=clean),
                           org_id=org_id, prompt_key=prompt.key, prompt_version=prompt.version, json_output=True,
                           mock_response=json.dumps(heuristic(job, cv)), temperature=0)
        a = r.data if isinstance(r.data, dict) else heuristic(job, cv)
    except AllModelsFailed:
        a = heuristic(job, cv)
    return checked(a, cv, job)


async def add_candidate(org_id: str, job_id: str, data: bytes, filename: str, *, source: str = "upload", name: str | None = None,
                        email: str | None = None, phone: str | None = None) -> dict:
    try:
        cv = extract_text(filename, data)
    except UnreadableFile as e:
        raise ValueError(str(e)) from e
    async with tenant_session(org_id) as conn:
        job = (await conn.execute(text("select * from app.jobs where id = cast(:j as uuid)"), {"j": job_id})).mappings().first()
        if not job or job["status"] == "closed":
            raise ValueError("this job isn't open")
    a = await score(org_id, dict(job), cv)
    path = folder(org_id) / f"{uuid.uuid4()}{Path(filename).suffix.lower()}"
    path.write_bytes(data)
    async with tenant_session(org_id) as conn:
        _s, cfg = await settings_of(conn)
        from agentry.leads import resolve_contact
        nm, em, ph = name or a.get("name"), email or a.get("email"), phone or a.get("phone")
        contact = await resolve_contact(conn, org_id, name=nm, email=em, phone=ph, source="hiring") if (em or ph) else None
        cid = str((await conn.execute(text("""insert into app.candidates (org_id, job_id, contact_id, name, email, phone, source, filename, path, cv_text, score,
            verdict, assessment) values (:o, cast(:j as uuid), cast(:k as uuid), :n, :e, :p, :s, :f, :pa, :cv, :sc, :v, cast(:a as jsonb)) returning id"""),
            {"o": org_id, "j": job_id, "k": contact, "n": nm, "e": em, "p": ph, "s": source, "f": filename, "pa": str(path.relative_to(Path(settings.documents_dir))),
             "cv": cv[:50000], "sc": a["score"], "v": a["verdict"], "a": json.dumps({k: a.get(k) for k in ("summary", "strengths", "gaps", "questions", "years_experience")})})).scalar_one())
        await emit(conn, org_id, "candidate.screened", {"candidate_id": cid, "job_id": job_id, "score": a["score"], "verdict": a["verdict"]})
        if a["verdict"] == "strong" and cfg["shortlist_cards"]:
            await conn.execute(text("""insert into app.approvals (org_id, kind, automation_key, title, body, payload)
                values (:o, 'escalation', 'hiring', :t, :b, cast(:p as jsonb))"""),
                {"o": org_id, "t": f"Strong candidate for {job['title']}: {nm or 'unnamed'} ({a['score']}/100)", "b": a.get("summary") or "",
                 "p": json.dumps({"candidate_id": cid, "job_id": job_id})})
    return {"id": cid, "score": a["score"], "verdict": a["verdict"], "name": nm}


async def set_stage(conn: AsyncConnection, org_id: str, cid: str, status: str, *, interview_at: datetime | None, user_id: str | None) -> dict:
    from agentry.outbound import reach_contact
    c = (await conn.execute(text("""select c.*, j.title from app.candidates c join app.jobs j on j.id = c.job_id where c.id = cast(:i as uuid) for update"""),
                            {"i": cid})).mappings().first()
    if not c:
        raise ValueError("candidate not found")
    if status not in ("new", "shortlisted", "interview", "offered", "hired", "rejected"):
        raise ValueError("unknown stage")
    if status == "interview" and not interview_at:
        raise ValueError("pick the interview time")
    await conn.execute(text("update app.candidates set status = :s, interview_at = coalesce(:t, interview_at), updated_at = now() where id = :i"),
                       {"s": status, "t": interview_at, "i": c["id"]})
    await audit.record(conn, org_id=org_id, actor_type="user", actor_user_id=user_id, action=f"candidate.{status}", target_type="candidate", target_id=cid)
    _s, cfg = await settings_of(conn)
    business = (await conn.execute(text("select name from auth.organization where id = :o"), {"o": org_id})).scalar_one_or_none() or ""
    tz = (await conn.execute(text("select timezone from app.org_settings"))).scalar_one_or_none() or "Asia/Kolkata"
    first = (c["name"] or "there").split()[0]
    body = None
    if status == "interview":
        from zoneinfo import ZoneInfo
        local = interview_at.astimezone(ZoneInfo(tz))
        body = (f"Hi {first}, thank you for applying for {c['title']} at {business}. We'd like to meet you on {local:%A %d %B} at {local:%I:%M %p}"
                f" at {cfg['interview_place']}. Please reply here to confirm, or suggest another time.")
    elif status == "rejected" and cfg["send_regrets"] and c["status"] != "rejected":
        body = (f"Hi {first}, thank you for your interest in {c['title']} at {business} and for the time you took to apply. "
                "We've decided to go ahead with other candidates for this role, but we'll keep your CV in mind. We wish you the very best.")
    sent = None
    if body and c["contact_id"]:
        k = (await conn.execute(text("""select id::text as contact_id, name as contact_name, phone_e164, email, attributes->>'telegram_id' as telegram_id
            from app.contacts where id = :k"""), {"k": c["contact_id"]})).mappings().one()
        sent = (await reach_contact(conn, org_id, dict(k), body, agent="hiring", subject=f"Your application for {c['title']}",
                                    email_ref=f"candidate:{cid}"))["status"]
    return {"id": cid, "status": status, "message": sent}

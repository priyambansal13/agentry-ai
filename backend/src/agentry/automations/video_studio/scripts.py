"""Topic -> script (ROADMAP-V3 A6): a timed script the owner films on a phone; or hand it to the AI video studio.

The writer (OpenAI first) uses the business's services, brand and call to action; the same rules as the studio's
plans (no invented prices, offers, numbers or guarantees) are checked on what it returns, with one rewrite.
"""
import json

from sqlalchemy import text

from agentry.automations import video_studio as vs
from agentry.db import tenant_session
from agentry.llm.gateway import AllModelsFailed, complete
from agentry.llm.prompts import load


def _mock(topic: str, business: str, cta: str | None) -> dict:
    return {"hook": f"Here's what nobody tells you about {topic.lower()}"[:80],
            "beats": [{"at": "0-3s", "say": f"Here's what nobody tells you about {topic.lower()}.", "show": "You, close to the camera", "on_screen": topic[:40]},
                      {"at": "3-15s", "say": "Most people only find out when it's too late.", "show": "Your workplace", "on_screen": ""},
                      {"at": "15-35s", "say": "Here's how we handle it, step by step.", "show": "You at work", "on_screen": "Step by step"},
                      {"at": "35-45s", "say": cta or f"Message {business} if you'd like help.", "show": "You, smiling", "on_screen": ""}],
            "cta": cta or f"Message {business} if you'd like help.", "caption": f"{topic}. Save this for later.",
            "hashtags": ["#Shorts", "#SmallBusiness", "#Tips", "#India"], "seconds": 45}


def problems(s: dict) -> list[str]:
    out = []
    if not s.get("hook") or not isinstance(s.get("beats"), list) or not 3 <= len(s["beats"]) <= 8:
        out.append("needs a hook and 4-7 beats")
    words = " ".join([s.get("hook") or "", s.get("cta") or "", s.get("caption") or "",
                      *[f"{b.get('say', '')} {b.get('on_screen', '')}" for b in s.get("beats") or [] if isinstance(b, dict)]])
    if m := vs.RISKY.search(words):
        out.append(f"risky wording: \"{m.group(0)}\"")
    return out


async def write(org_id: str, topic: str | None, user_id: str | None = None) -> dict:
    async with tenant_session(org_id) as conn:
        _st, cfg = await vs.settings_of(conn)
        ctx = await vs.context(conn, org_id, cfg)
    ideas = [t for t in cfg["topics"] if t.lower() not in {r.lower() for r in ctx["recent"]}] or cfg["topics"]
    topic = (topic or (ideas[0] if ideas else None) or (ctx["services"].split(",")[0] if ctx["services"] != "(not listed)" else "A day at our work")).strip()[:200]
    prompt = load("video_script")
    script, issues = {}, []
    for _ in range(2):
        msgs = prompt.render(business=ctx["business"], about=ctx["about"], services=ctx["services"], topic=topic, language=cfg["language"],
                             cta=cfg["call_to_action"] or "(none)")
        if issues:
            msgs.append({"role": "user", "content": "Fix these problems: " + "; ".join(issues)})
        try:
            r = await complete(prompt.tier, msgs, org_id=org_id, prompt_key=prompt.key, prompt_version=prompt.version, json_output=True,
                               mock_response=json.dumps(_mock(topic, ctx["business"], cfg["call_to_action"])), temperature=0.7, prefer=cfg["planner"])
            script = r.data if isinstance(r.data, dict) else {}
        except AllModelsFailed as e:
            raise ValueError("the writing models are busy: try again in a few minutes") from e
        issues = problems(script)
        if not issues:
            break
    if issues:
        raise ValueError("couldn't write a safe script for that topic: " + "; ".join(issues))
    tags = [t if t.startswith("#") else f"#{t}" for t in script.get("hashtags") or []]
    script["hashtags"] = (["#Shorts"] + [t for t in tags if t.lower() != "#shorts"])[:6]
    async with tenant_session(org_id) as conn:
        sid = str((await conn.execute(text("""insert into app.video_scripts (org_id, topic, language, script, created_by) values (:o, :t, :l, cast(:s as jsonb), :u)
            returning id"""), {"o": org_id, "t": topic, "l": cfg["language"], "s": json.dumps(script), "u": user_id})).scalar_one())
    return {"id": sid, "topic": topic, "script": script}

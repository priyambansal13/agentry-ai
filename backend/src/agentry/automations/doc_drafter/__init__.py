"""SOP & proposal drafter (ROADMAP-V3 B4, v2 11.5): one brief -> a procedure with a flowchart, a proposal or a checklist.

    sop        purpose, roles, numbered steps (who / done when), checks, records, risks + a Mermaid flowchart
    proposal   scope, deliverables, timeline, price: only prices from the brief or the business's services, else
               "[price to confirm]" (a number that isn't in the brief or the services is flagged and rewritten once)
    checklist  grouped tick boxes with who and when (an onboarding, an opening / closing routine)
Edit in the portal, mark final, download Markdown or HTML.
"""
import json
import re

from pydantic import BaseModel
from sqlalchemy import text

from agentry.automations import AutomationTemplate, register
from agentry.db import tenant_session
from agentry.llm.gateway import AllModelsFailed, complete
from agentry.llm.prompts import load

NUM = re.compile(r"(₹|rs\.?|inr)\s?[\d,]+(\.\d+)?|\b\d+\s?%|\b\d+\s?(days|weeks|months)\b", re.IGNORECASE)


class DocConfig(BaseModel):
    pass


register(AutomationTemplate(
    key="doc_drafter", name="SOP & proposal drafter",
    description="One brief becomes a step-by-step SOP with a flowchart, a client proposal or a checklist, without invented prices or dates.",
    config_model=DocConfig, metrics=(),
))


def problems(d: dict, allowed: str, kind: str) -> list[str]:
    out = []
    if not d.get("content") or len(d["content"].split()) < 60:
        out.append("the document is missing or too short")
    if kind == "sop" and "flowchart" not in (d.get("diagram") or ""):
        out.append("the SOP needs a flowchart")
    ok = re.sub(r"[,\s]", "", allowed.lower())
    for m in NUM.finditer(d.get("content") or ""):
        digits = re.sub(r"[^\d.]", "", m.group(0))
        if digits and digits not in ok:
            out.append(f"\"{m.group(0)}\" isn't in the brief")
            break
    return out


def _mock(kind: str, brief: str) -> dict:
    t = brief.split(".")[0][:60] or kind
    steps = "\n".join(f"{i}. Step {i} of: {brief[:60]} (who: owner; done when: checked)" for i in range(1, 7))
    body = {"sop": f"## Purpose\n{brief}\n\n## Who does it\nOwner, front desk.\n\n## Steps\n{steps}\n\n## Checks\nThe owner checks the work weekly.\n\n## Records to keep\nA log.",
            "proposal": f"## Summary\n{brief}\n\n## What we'll do\nThe work described.\n\n## Price\n[price to confirm]\n\n## Next step\nReply to confirm and we'll start. " + "Details follow. " * 20,
            "checklist": "## Day 1\n" + "\n".join(f"- [ ] Item {i} (owner)" for i in range(1, 9)) + "\n\n## Week 1\n" + "\n".join(f"- [ ] Item {i} (manager)" for i in range(9, 15))}[kind]
    return {"title": t, "content": body, "diagram": 'flowchart TD\n  A["Start"] --> B["Do the work"] --> C{"Done right?"}\n  C -- yes --> D["Record it"]\n  C -- no --> B' if kind == "sop" else ""}


async def draft(org_id: str, kind: str, brief: str, user_id: str | None) -> dict:
    if kind not in ("sop", "proposal", "checklist"):
        raise ValueError("sop, proposal or checklist")
    async with tenant_session(org_id) as conn:
        business = (await conn.execute(text("select name from auth.organization where id = :o"), {"o": org_id})).scalar_one_or_none() or ""
        services = (await conn.execute(text("select name, price from app.services where active order by name limit 30"))).all()
    facts = "; ".join(f"{s.name}{f' (₹{float(s.price):g})' if s.price else ''}" for s in services) or "(none)"
    prompt = load("doc_draft")
    d, probs = {}, []
    for _ in range(2):
        msgs = prompt.render(business=business, kind=kind, brief=brief, facts=facts)
        if probs:
            msgs.append({"role": "user", "content": "Fix these problems: " + "; ".join(probs)})
        try:
            r = await complete(prompt.tier, msgs, org_id=org_id, prompt_key=prompt.key, prompt_version=prompt.version, json_output=True,
                               mock_response=json.dumps(_mock(kind, brief)), temperature=0.4)
            d = r.data if isinstance(r.data, dict) else {}
        except AllModelsFailed as e:
            raise ValueError("the writing models are busy: try again in a few minutes") from e
        probs = problems(d, f"{brief} {facts}", kind)
        if not probs:
            break
    async with tenant_session(org_id) as conn:
        did = str((await conn.execute(text("""insert into app.doc_drafts (org_id, kind, title, brief, content, diagram, checks, status, created_by)
            values (:o, :k, :t, cast(:b as jsonb), :c, :dg, cast(:ch as jsonb), :s, :u) returning id"""),
            {"o": org_id, "k": kind, "t": (d.get("title") or kind.title())[:160], "b": json.dumps({"brief": brief}), "c": d.get("content") or "",
             "dg": d.get("diagram") or None, "ch": json.dumps(probs), "s": "needs_attention" if probs else "draft", "u": user_id})).scalar_one())
    return {"id": did, "status": "needs_attention" if probs else "draft", "problems": probs}

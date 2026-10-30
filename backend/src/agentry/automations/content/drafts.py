"""One post per moment and platform (Phase 6.2): a small LangGraph loop, draft -> critic -> rewrite (at most twice).

The critic is mostly rules, because rules can't be talked round: anything in quotation marks must be in the transcript
word for word, every number must appear in the moment's context, the platform's length and hashtag limits hold, the
first line is a real hook, and none of the usual AI filler. The `fast` model then gives a second opinion on invented
claims and tone. A post that still fails after two rewrites is kept for a person, marked "needs attention".
"""
import json
import re
from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from agentry.automations.content.moments import norm, quote_in
from agentry.llm.gateway import AllModelsFailed, complete
from agentry.llm.prompts import load

RULES = {
    "linkedin": {"max": 3000, "aim": "600-900 characters", "hashtags": (0, 3),
                 "shape": "a hook line, short paragraphs (1-2 sentences), one takeaway, a soft question or call to action at the end"},
    "instagram": {"max": 2200, "aim": "300-600 characters", "hashtags": (3, 10),
                  "shape": "a hook line, 2-4 short lines, a call to action (save, share, book); hashtags go in the hashtags list"},
    "x": {"max": 280, "aim": "under 280 characters including hashtags", "hashtags": (0, 2),
          "shape": "one punchy post: the hook or the quote, nothing else"},
}
FILLER = re.compile(r"game[- ]changer|unlock|delve|in today'?s fast[- ]paced|elevate your|let'?s dive in|buckle up|revolutioni[sz]e",
                    re.IGNORECASE)
QUOTED = re.compile(r"[\"“]([^\"”]{12,})[\"”]")


class PostState(TypedDict, total=False):
    org_id: str
    platform: str
    moment: dict
    context: str
    transcript: str
    voice: str
    body: str
    hashtags: list[str]
    problems: list[str]
    attempts: int


def _short_quote(quote: str, limit: int) -> str:
    """Whole sentences of the quote that fit (so the shortened quote is still exact)."""
    out = ""
    for sent in re.split(r"(?<=[.!?])\s+", quote.strip()):
        if len(out) + len(sent) + 1 > limit:
            break
        out = f"{out} {sent}".strip()
    return out or quote[:limit]


def template_post(platform: str, m: dict) -> dict:
    """The offline draft (tests, or models down): honest and plain, built only from the moment itself."""
    who = m.get("speaker") or "our guest"
    tags = {"linkedin": ["leadership"], "instagram": ["smallbusiness", "clinicowner", "patientcare", "businesstips"], "x": []}[platform]
    if platform == "linkedin":
        body = f"{m['hook']}\n\n“{m['quote']}”\n— {who}\n\n{m['insight']}\n\nWhat would you add?"
    elif platform == "instagram":
        body = f"{m['hook']}\n\n“{m['quote']}”\n\n{m['insight']}\n\nSave this for later."
    else:
        q = _short_quote(m["quote"], 240 - len(who))
        body = f"“{q}” — {who}"
    return {"body": body, "hashtags": tags}


def check(platform: str, body: str, hashtags: list[str], moment: dict, context: str, transcript: str) -> list[str]:
    """Rule-based critic. Returns the problems (empty = passes)."""
    r, problems = RULES[platform], []
    total = len(body) + sum(len(h) + 2 for h in hashtags)
    if total > r["max"]:
        problems.append(f"too long for {platform}: {total} characters (limit {r['max']})")
    lo, hi = r["hashtags"]
    if not lo <= len(hashtags) <= hi:
        problems.append(f"use {lo}-{hi} hashtags on {platform} (has {len(hashtags)})")
    first = body.strip().splitlines()[0] if body.strip() else ""
    if not first or (platform != "x" and len(first) > 140):  # an X post is one line: its limit is the 280 above
        problems.append("the first line must be a short hook (under 140 characters)")
    for q in QUOTED.findall(body):
        if not quote_in(q, transcript):
            problems.append(f"quote not found word for word in the recording: \"{q[:60]}\"")
    source = norm(f"{moment['quote']} {context}").replace(",", "")
    for n in re.findall(r"\d[\d,.]*%?", body):
        digits = n.replace(",", "").rstrip(".%")  # "22%" is fine when the recording says "22 percent"
        if not re.search(rf"(?<![\d.]){re.escape(digits)}(?![\d])", source):
            problems.append(f"the number {n} isn't in the recording around this moment")
    if FILLER.search(body):
        problems.append(f"sounds like AI filler: \"{FILLER.search(body).group(0)}\"")
    return problems


async def _write(state: PostState) -> PostState:
    m, platform = state["moment"], state["platform"]
    prompt = load("content_post")
    r = RULES[platform]
    feedback = ("\nYour previous draft was rejected for: " + "; ".join(state["problems"]) + ". Fix exactly that.") if state.get("problems") else ""
    fallback = template_post(platform, m)
    try:
        res = await complete(prompt.tier, prompt.render(platform=platform, rules=f"{r['shape']}; length {r['aim']}; {r['hashtags'][0]}-{r['hashtags'][1]} hashtags",
                                                        voice=state.get("voice") or "", hook=m["hook"], insight=m["insight"],
                                                        speaker=m.get("speaker") or "speaker", quote=m["quote"], context=state["context"][:1500],
                                                        feedback=feedback),
                             org_id=state["org_id"], prompt_key=prompt.key, prompt_version=prompt.version, json_output=True,
                             mock_response=json.dumps(fallback))
        data = res.data if isinstance(res.data, dict) and res.data.get("body") else fallback
    except AllModelsFailed:
        data = fallback
    tags = [re.sub(r"[^\w]", "", str(h)) for h in (data.get("hashtags") or [])]
    return {"body": str(data["body"]).strip(), "hashtags": [t for t in tags if t][:12], "attempts": state.get("attempts", 0) + 1}


async def _critic(state: PostState) -> PostState:
    m = state["moment"]
    problems = check(state["platform"], state["body"], state["hashtags"], m, state["context"], state["transcript"])
    if not problems:
        prompt = load("content_critic")
        try:
            res = await complete(prompt.tier, prompt.render(platform=state["platform"], quote=m["quote"], context=state["context"][:1500],
                                                            body=state["body"]), org_id=state["org_id"], prompt_key=prompt.key,
                                 prompt_version=prompt.version, json_output=True, mock_response=json.dumps({"pass": True, "problems": []}))
            data = res.data if isinstance(res.data, dict) else {}
            if data.get("pass") is False:
                problems = [str(p)[:160] for p in (data.get("problems") or ["the reviewer model flagged it"])][:3]
        except AllModelsFailed:
            pass
    return {"problems": problems}


def _again(state: PostState) -> str:
    return "write" if state["problems"] and state["attempts"] < 3 else END


def _graph():
    g = StateGraph(PostState)
    g.add_node("write", _write)
    g.add_node("critic", _critic)
    g.add_edge(START, "write")
    g.add_edge("write", "critic")
    g.add_conditional_edges("critic", _again)
    return g.compile()


GRAPH = _graph()


async def draft_post(org_id: str, platform: str, moment: dict, context: str, transcript: str, voice: str | None) -> dict:
    """{body, hashtags, ok, problems, attempts}"""
    out = await GRAPH.ainvoke({"org_id": org_id, "platform": platform, "moment": moment, "context": context, "transcript": transcript,
                               "voice": voice or "", "problems": [], "attempts": 0})
    return {"body": out["body"], "hashtags": out["hashtags"], "ok": not out["problems"], "problems": out["problems"], "attempts": out["attempts"]}

"""Who to write to, what's true about them, and one first line that only uses what's true.

1. people_on_site: people the website names (model `fast`, with a pattern-based fallback). Emails the model returns
   are kept only if they appear on the pages word for word: a model never invents an address.
2. decision_maker: the person to write to. Their own address from the site, else the finder, else a guess at
   first@domain that the pipeline keeps only if the verifier says "valid".
3. snippets: short facts from their own pages (the only facts a first line may use), numbered and stored.
4. write_line + check_line: the `writer` model picks one snippet; a fact check (a word check here, then the `fast`
   model) refuses anything the snippet doesn't say. One rewrite with the reason, then a person decides.
"""
import json
import re
from dataclasses import dataclass

from agentry.automations.cold_email.providers import FoundPerson, Providers, SitePage
from agentry.llm.gateway import AllModelsFailed, complete
from agentry.llm.prompts import load

GENERIC = {"info", "contact", "contactus", "hello", "hi", "admin", "reception", "appointment", "appointments", "enquiry",
           "enquiries", "inquiries", "support", "office", "mail", "help", "care", "booking", "bookings", "frontdesk",
           "team", "clinic", "sales", "accounts", "billing", "hr", "careers", "jobs", "noreply", "no-reply", "marketing"}
DECIDES = re.compile(r"\b(founder|co-?founder|owner|director|partner|principal|proprietor|chief|head|ceo|managing|md|"
                     r"chairman|president)\b", re.IGNORECASE)
EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
PERSON_LINE = re.compile(r"^(?:Dr\.?\s+|Mr\.?\s+|Ms\.?\s+|Mrs\.?\s+)?(?P<name>[A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,2})\s*,\s*"
                         r"(?P<role>[^—–\n@]+?)\s*(?:[—–-]+\s*(?P<email>[\w.+-]+@[\w-]+(?:\.[\w-]+)+))?\s*$", re.MULTILINE)


@dataclass
class Person:
    name: str | None
    role: str | None
    email: str | None

    @property
    def decides(self) -> bool:
        return bool(self.role and DECIDES.search(self.role))


def is_generic(email: str) -> bool:
    return email.split("@", 1)[0].lower().replace(".", "") in GENERIC


def _pages_text(pages: list[SitePage], limit: int = 6000) -> str:
    return "\n\n".join(f"[{p.url}]\n{p.text}" for p in pages)[:limit]


def people_by_pattern(pages: list[SitePage]) -> list[Person]:
    out: list[Person] = []
    for p in pages:
        for m in PERSON_LINE.finditer(p.text):
            out.append(Person(m["name"], m["role"].strip(), (m["email"] or "").lower() or None))
    return out


async def people_on_site(org_id: str, business: str, domain: str, pages: list[SitePage]) -> list[Person]:
    if not pages:
        return []
    fallback = people_by_pattern(pages)
    prompt = load("cold_email_people")
    try:
        res = await complete(prompt.tier, prompt.render(business=business, domain=domain, pages=_pages_text(pages)), org_id=org_id,
                             prompt_key=prompt.key, prompt_version=prompt.version, json_output=True,
                             mock_response=json.dumps({"people": [p.__dict__ for p in fallback]}))
        raw = (res.data or {}).get("people") if isinstance(res.data, dict) else None
    except AllModelsFailed:
        raw = None
    if not isinstance(raw, list):
        return fallback
    seen = _pages_text(pages, limit=10**6).lower()
    people = []
    for r in raw:
        if not isinstance(r, dict) or not r.get("name"):
            continue
        email = (r.get("email") or "").strip().lower() or None
        people.append(Person(str(r["name"]).strip(), (r.get("role") or None), email if email and email in seen else None))
    return people


@dataclass
class Choice:
    email: str
    name: str | None
    role: str | None
    source: str  # site | finder | pattern


def _first(name: str | None) -> str | None:
    return name.split()[0] if name else None


async def decision_maker(providers: Providers, domain: str, people: list[Person],
                         pages: list[SitePage] | None = None) -> tuple[Choice | None, str]:
    """The person to write to, or (None, why not)."""
    on_domain = [p for p in people if p.email and p.email.endswith("@" + domain)]
    for p in on_domain:
        if p.decides and not is_generic(p.email):
            return Choice(p.email, p.name, p.role, "site"), ""
    found: list[FoundPerson] = [f for f in await providers.find_people(domain)
                                if f.email.lower().endswith("@" + domain) and not is_generic(f.email)]
    deciders = [p for p in people if p.decides and p.name]
    names = {p.name.lower() for p in deciders}
    found.sort(key=lambda f: (-(bool(f.name and f.name.lower() in names)), -bool(f.role and DECIDES.search(f.role)), -f.confidence))
    if found:
        f = found[0]
        named = next((p for p in deciders if f.name and p.name.lower() == f.name.lower()), None)
        return Choice(f.email.lower(), f.name, f.role or (named.role if named else None), "finder"), ""
    if deciders:
        p = deciders[0]
        return Choice(f"{_first(p.name).lower()}@{domain}", p.name, p.role, "pattern"), ""
    on_pages = EMAIL.findall(" ".join(p.text for p in pages or []))
    if any(is_generic(e) for e in [*on_pages, *(p.email for p in people if p.email)]):  # a model leaves info@ out of "people"
        return None, "only a generic inbox (info@...)"
    return None, "no decision maker named"


# ---------- facts from their website ----------

_SKIP = re.compile(r"@|https?://|\bcall\b|\+?\d[\d\s-]{8,}|cookie|privacy|copyright|©", re.IGNORECASE)
_STRONG = re.compile(r"\b(first|since|founded|years?|award|only|over|more than|introduced|launched|opened|specialis|certified)\b", re.IGNORECASE)


def snippets(pages: list[SitePage], limit: int = 6) -> list[dict]:
    """Short factual sentences from their pages, best first: the only material a first line may draw on."""
    scored, seen = [], set()
    for page_i, p in enumerate(pages):
        for block in p.text.split("\n"):
            for sent in re.split(r"(?<=[.!?])\s+", block.strip()):
                s = sent.strip()
                if not 30 <= len(s) <= 220 or _SKIP.search(s) or PERSON_LINE.match(s) or s.lower() in seen:
                    continue
                seen.add(s.lower())
                score = 2 * bool(re.search(r"\d", s)) + 2 * bool(_STRONG.search(s)) + ("about" in p.url) - page_i * 0.01
                scored.append((score, p.url, s))
    scored.sort(key=lambda t: -t[0])
    return [{"n": i + 1, "url": url, "text": s} for i, (_, url, s) in enumerate(scored[:limit])]


# ---------- the first line and its fact check ----------

_YOU = [(r"\bWe were\b", "you were"), (r"\bwe were\b", "you were"), (r"\bWe\b", "you"), (r"\bwe\b", "you"),
        (r"\bOur\b", "your"), (r"\bour\b", "your"), (r"\bus\b", "you")]


def heuristic_line(business: str, snip: dict) -> str:
    """A plain, grounded line (the offline fallback): the fact itself, turned to "you"."""
    t = snip["text"].rstrip(".!")
    m = re.match(r"Founded in (\d{4}),\s*(.+?)\s+has\s+(.+)", t)
    if m:
        return f"Read that {m[2]} has {m[3]} since {m[1]}."
    for pat, rep in _YOU:
        t = re.sub(pat, rep, t)
    return f"Read on your website that {t[0].lower() + t[1:]}."


STOP = {"read", "website", "noticed", "saw", "your", "you", "that", "this", "with", "have", "been", "were", "they", "their",
        "from", "about", "which", "really", "love", "loved", "great", "nice", "just", "what", "when", "also", "into", "there",
        "here", "since", "more", "than", "has", "had", "the", "and", "for", "are", "was", "who", "how", "being", "page", "site",
        "came", "across", "looks", "like", "seems", "clinic", "clinics", "team", "practice", "business", "patients", "patient"}


def _words(s: str) -> list[str]:
    return [w.rstrip("s") if len(w) > 4 else w for w in re.findall(r"[a-z0-9][a-z0-9,'-]*", s.lower().replace(",", ""))]


def word_check(line: str, snippet: str, business: str = "") -> tuple[bool, str]:
    """Every number in the line must be in the snippet, and most of its content words must be too."""
    src = set(_words(snippet)) | set(_words(business))
    nums = [w for w in re.findall(r"\d[\d,]*", line.replace(",", "")) if w not in snippet.replace(",", "")]
    if nums:
        return False, f"mentions {', '.join(nums)}, which the website fact doesn't"
    claims = [w for w in _words(line) if len(w) >= 4 and w not in STOP]
    missing = [w for w in claims if w not in src]
    if claims and len(missing) / len(claims) > 0.3:
        return False, f"says things the website fact doesn't: {', '.join(missing[:4])}"
    if re.search(r"\b(best|award|top-rated|leading|no\.? ?1|number one)\b", line, re.IGNORECASE) and not re.search(
            r"\b(best|award|top-rated|leading|no\.? ?1|number one)\b", snippet, re.IGNORECASE):
        return False, "makes a claim (best, award, leading) the website doesn't"
    return True, ""


async def check_line(org_id: str, line: str, snip: dict, business: str) -> tuple[bool, str]:
    ok, why = word_check(line, snip["text"], business)
    if not ok:
        return False, why
    prompt = load("cold_email_fact_check")
    try:
        res = await complete(prompt.tier, prompt.render(line=line, snippet=snip["text"]), org_id=org_id, prompt_key=prompt.key,
                             prompt_version=prompt.version, json_output=True, mock_response=json.dumps({"supported": True, "reason": ""}))
        data = res.data if isinstance(res.data, dict) else {}
    except AllModelsFailed:
        return True, ""  # the word check already passed; the model check is a second opinion
    if data.get("supported") is False:
        return False, str(data.get("reason") or "the fact checker found a claim the website doesn't make")[:200]
    return True, ""


async def write_line(org_id: str, *, business: str, first_name: str | None, role: str | None, snips: list[dict]) -> dict:
    """{line, snippet, ok, reason, attempts}: a line that passed the check, or the last attempt and why it failed."""
    if not snips:
        return {"line": None, "snippet": None, "ok": False, "reason": "nothing on their website to base a line on", "attempts": 0}
    prompt = load("cold_email_first_line")
    listed = "\n".join(f"{s['n']}. {s['text']}" for s in snips)
    feedback, last = "", {}
    for attempt in (1, 2):
        fallback = {"line": heuristic_line(business, snips[0]), "snippet": snips[0]["n"]}
        try:
            res = await complete(prompt.tier, prompt.render(first_name=first_name or "the owner", role=role or "owner", business=business,
                                                            snippets=listed, feedback=feedback),
                                 org_id=org_id, prompt_key=prompt.key, prompt_version=prompt.version, json_output=True,
                                 mock_response=json.dumps(fallback))
            data = res.data if isinstance(res.data, dict) and res.data.get("line") else fallback
        except AllModelsFailed:
            data = fallback
        line = re.sub(r"\s+", " ", str(data["line"])).strip()
        snip = next((s for s in snips if str(s["n"]) == str(data.get("snippet"))), None)
        if not snip:
            ok, why = False, "didn't say which website fact it uses"
        else:
            ok, why = await check_line(org_id, line, snip, business)
        last = {"line": line, "snippet": snip["n"] if snip else None, "ok": ok, "reason": why, "attempts": attempt}
        if ok:
            return last
        feedback = (f"\nYour previous line was rejected: \"{line}\" ({why}). Write a new one that only uses words and facts "
                    "from one numbered fact.")
    return last

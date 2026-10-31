"""Building a cold-email list: one durable workflow per campaign, one step per business.

    found -> has a website -> fits the ideal customer -> new to us -> decision maker found -> email verified -> first line ready

Each business records the furthest step it reached and, if it stopped, why (prospect_companies.reached/drop_reason),
so the funnel on the Campaigns page is counted from the rows themselves. People who pass verification become
prospects with their research snippets and first line, waiting for review (5.3). Nothing is sent from here (5.4).
"""
import json
from urllib.parse import urlparse

from dbos import DBOS, SetWorkflowID
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from agentry.automations.cold_email import providers as prov
from agentry.automations.cold_email import research
from agentry.db import system_session, tenant_session
from agentry.events import emit
from agentry.leads import normalize_email
from agentry.runs import run

STAGES = ["found", "website", "fits", "new", "decision_maker", "verified", "ready"]
STAGE_LABELS = {"found": "Businesses found", "website": "Have a website", "fits": "Fit your ideal customer",
                "new": "New to you", "decision_maker": "Decision maker found", "verified": "Email verified",
                "ready": "First line ready"}
# EU/UK are off by default (docs/PHASE-5-COLD-EMAIL.md §5): a legitimate-interest note per campaign is needed first
EU_UK = {"uk", "co.uk", "ie", "de", "fr", "es", "it", "nl", "be", "lu", "at", "dk", "se", "fi", "pt", "pl", "cz", "gr", "hu",
         "ro", "bg", "hr", "si", "sk", "lt", "lv", "ee", "cy", "mt", "eu"}


def domain_of(url: str | None) -> str | None:
    if not url:
        return None
    host = urlparse(url if "://" in url else "https://" + url).hostname or ""
    return host.lower().removeprefix("www.") or None


def _in_eu_uk(domain: str) -> bool:
    parts = domain.split(".")
    return parts[-1] in EU_UK or ".".join(parts[-2:]) in EU_UK


# ---------- creating a campaign ----------

async def create_campaign(conn: AsyncConnection, org_id: str, *, name: str, settings: dict, user_id: str | None,
                          rows: list[dict] | None = None) -> str:
    """settings: {source: places|csv, query, city, limit, min_rating, min_reviews, allow_catch_all, allow_eu_uk}.
    CSV rows (name, website, category, rating, reviews, city...) become the businesses found; Places searches at build time."""
    cid = str((await conn.execute(text("""insert into app.campaigns (org_id, kind, name, status, settings, build_status, created_by, stats)
        values (:o, 'cold_email', :n, 'draft', cast(:s as jsonb), 'building', :u, '{}') returning id"""),
        {"o": org_id, "n": name, "s": json.dumps(settings), "u": user_id})).scalar_one())
    for i, r in enumerate(rows or []):
        await _insert_company(conn, org_id, cid, "csv", {**r, "place_id": r.get("place_id") or f"csv-{i + 1}"})
    await emit(conn, org_id, "cold_email.build_requested", {"campaign_id": cid})
    return cid


async def _insert_company(conn: AsyncConnection, org_id: str, campaign_id: str, source: str, b: dict) -> None:
    def num(v, cast):
        try:
            return cast(v) if v not in (None, "") else None
        except (TypeError, ValueError):
            return None
    website = (b.get("website") or "").strip() or None
    await conn.execute(text("""insert into app.prospect_companies (org_id, campaign_id, source, place_id, name, website, domain,
        category, rating, reviews, city, address, phone) values (:o, :c, :src, :p, :n, :w, :d, :cat, :r, :rv, :city, :a, :ph)
        on conflict (campaign_id, place_id) do nothing"""),
        {"o": org_id, "c": campaign_id, "src": source, "p": b["place_id"], "n": (b.get("name") or "?").strip()[:200], "w": website,
         "d": domain_of(website), "cat": b.get("category"), "r": num(b.get("rating"), float), "rv": num(b.get("reviews"), int),
         "city": b.get("city"), "a": b.get("address"), "ph": b.get("phone")})


# ---------- the build ----------

@DBOS.step()
async def find_businesses(org_id: str, campaign_id: str) -> list[str]:
    """Search (Places) unless the businesses were imported, then return those not yet researched."""
    async with tenant_session(org_id) as conn:
        s = (await conn.execute(text("select settings from app.campaigns where id = cast(:c as uuid)"), {"c": campaign_id})).scalar_one()
        have = (await conn.execute(text("select count(*) from app.prospect_companies where campaign_id = cast(:c as uuid)"),
                                   {"c": campaign_id})).scalar_one()
        if not have and s.get("source", "places") == "places":
            for b in await prov.get().search(s.get("query") or "", s.get("city") or "", int(s.get("limit") or 50)):
                await _insert_company(conn, org_id, campaign_id, "places", b.__dict__)
        ids = (await conn.execute(text("""select id::text from app.prospect_companies where campaign_id = cast(:c as uuid)
            and reached = 0 and drop_reason is null order by created_at, name"""), {"c": campaign_id})).scalars().all()
        total = (await conn.execute(text("select count(*) from app.prospect_companies where campaign_id = cast(:c as uuid)"),
                                    {"c": campaign_id})).scalar_one()
        await conn.execute(text("update app.campaigns set stats = stats || cast(:s as jsonb) where id = cast(:c as uuid)"),
                           {"s": json.dumps({"total": total, "processed": total - len(ids)}), "c": campaign_id})
    return list(ids)


async def _known_domains(conn: AsyncConnection, org_id: str, campaign_id: str) -> set[str]:
    """Domains we must not cold-email: this business's contacts (clients, leads), earlier campaigns' prospects and,
    for Agentry's own campaigns, Agentry's clients."""
    emails = (await conn.execute(text("select email_norm from app.contacts where email_norm is not null and merged_into is null"))).scalars().all()
    known = {e.split("@", 1)[1] for e in emails if "@" in e}
    known |= set((await conn.execute(text("""select domain from app.prospect_companies where domain is not null
        and campaign_id <> cast(:c as uuid) and reached >= 3"""), {"c": campaign_id})).scalars().all())
    own = (await conn.execute(text("select website from app.org_settings"))).scalar_one_or_none()
    async with system_session() as sysconn:
        slug = (await sysconn.execute(text("select slug from auth.organization where id = :o"), {"o": org_id})).scalar_one_or_none()
        if slug == "agentry":
            sites = (await sysconn.execute(text("select website from app.org_settings where org_id <> :o and website is not null"),
                                           {"o": org_id})).scalars().all()
            known |= {d for d in (domain_of(w) for w in sites) if d}
    known.discard(domain_of(own) or "")
    return known


@DBOS.step()
async def research_company(org_id: str, campaign_id: str, company_id: str) -> dict:
    p = prov.get()
    async with tenant_session(org_id) as conn:
        c = (await conn.execute(text("select * from app.prospect_companies where id = cast(:i as uuid)"), {"i": company_id})).mappings().one()
        s = (await conn.execute(text("select settings from app.campaigns where id = cast(:c as uuid)"), {"c": campaign_id})).scalar_one()
        await conn.execute(text("delete from app.prospects where company_id = cast(:i as uuid)"), {"i": company_id})  # a retried step

        async def stop(reached: int, why: str | None) -> dict:
            await conn.execute(text("""update app.prospect_companies set reached = :r, drop_reason = :w where id = cast(:i as uuid)"""),
                               {"r": reached, "w": why, "i": company_id})
            await conn.execute(text("""update app.campaigns set stats = jsonb_set(stats, '{processed}',
                to_jsonb(coalesce((stats->>'processed')::int, 0) + 1)) where id = cast(:c as uuid)"""), {"c": campaign_id})
            return {"reached": STAGES[reached], "drop_reason": why}

        domain = c["domain"]
        if not c["website"] or not domain:
            return await stop(0, "no website")
        if s.get("min_rating") and c["rating"] is not None and float(c["rating"]) < float(s["min_rating"]):
            return await stop(1, f"rating below {s['min_rating']}")
        if s.get("min_reviews") and c["reviews"] is not None and c["reviews"] < int(s["min_reviews"]):
            return await stop(1, f"fewer than {s['min_reviews']} reviews")
        if not s.get("allow_eu_uk") and _in_eu_uk(domain):
            return await stop(1, "EU/UK business (off for this campaign)")
        if domain in await _known_domains(conn, org_id, campaign_id):
            return await stop(2, "already a client, lead or earlier prospect")
        pages = await p.read_site(c["website"])
        if not pages:
            return await stop(3, "couldn't read their website")
        people = await research.people_on_site(org_id, c["name"], domain, pages)
        choice, why = await research.decision_maker(p, domain, people, pages)
        if not choice:
            return await stop(3, why)
        email = normalize_email(choice.email) or choice.email
        suppressed = (await conn.execute(text("select 1 from app.suppressions where address = :a and channel in ('email','all')"),
                                         {"a": email})).first()
        if suppressed:
            return await stop(3, "on the do-not-contact list")
        verdict = await p.verify(email)
        if choice.source == "pattern" and verdict != "valid":
            return await stop(4, "guessed address couldn't be verified")
        if verdict != "valid" and not (verdict == "catch_all" and s.get("allow_catch_all")):
            return await stop(4, {"catch_all": "email can't be confirmed (catch-all domain)", "invalid": "email is invalid",
                                  "unknown": "email couldn't be checked"}[verdict])
        snips = research.snippets(pages)
        line = await research.write_line(org_id, business=c["name"], first_name=research._first(choice.name), role=choice.role, snips=snips)
        await conn.execute(text("""insert into app.prospects (org_id, campaign_id, company_id, name, role, email, email_source,
            verify_status, snippets, summary, first_line, line_snippet, fact_check, review)
            values (:o, cast(:c as uuid), cast(:co as uuid), :n, :r, :e, :src, :v, cast(:sn as jsonb), :sum, :l, :ls, cast(:fc as jsonb), :rev)
            on conflict (campaign_id, email) do nothing"""),
            {"o": org_id, "c": campaign_id, "co": company_id, "n": choice.name, "r": choice.role, "e": email, "src": choice.source,
             "v": verdict, "sn": json.dumps(snips), "sum": " ".join(x["text"] for x in snips[:3]) or None, "l": line["line"],
             "ls": line["snippet"], "fc": json.dumps({k: line[k] for k in ("ok", "reason", "attempts")}),
             "rev": "pending" if line["ok"] else "needs_attention"})
        return await stop(6 if line["ok"] else 5, None)  # a failed line isn't a drop: it waits in review as "needs attention"


@DBOS.step()
async def finish(org_id: str, campaign_id: str, status: str, error: str | None = None) -> None:
    async with tenant_session(org_id) as conn:
        await conn.execute(text("update app.campaigns set build_status = :s, build_error = :e where id = cast(:c as uuid)"),
                           {"s": status, "e": error, "c": campaign_id})
        await emit(conn, org_id, "cold_email.list_built", {"campaign_id": campaign_id, "status": status})


@DBOS.workflow()
async def build_list(org_id: str, campaign_id: str) -> str:
    async with run(org_id, "cold_email", "cold_email.list", key=f"cold_email:{campaign_id}", subject=("campaign", campaign_id)) as r:
        result = await _build_list(org_id, campaign_id)
        if result == "failed":
            r.fail("the list stopped part-way: see the campaign")
        return result


async def _build_list(org_id: str, campaign_id: str) -> str:
    try:
        for company_id in await find_businesses(org_id, campaign_id):
            await research_company(org_id, campaign_id, company_id)
    except Exception as e:  # noqa: BLE001 - shown on the campaign; the steps already done are kept
        await finish(org_id, campaign_id, "failed", str(e)[:300])
        return "failed"
    await finish(org_id, campaign_id, "built")
    return "built"


async def start_build(org_id: str, campaign_id: str) -> None:
    with SetWorkflowID(f"cold-email-build-{campaign_id}"):
        await DBOS.start_workflow_async(build_list, org_id, campaign_id)


# ---------- reading it back ----------

async def funnel(conn: AsyncConnection, campaign_id: str) -> dict:
    row = (await conn.execute(text("select " + ", ".join(f"count(*) filter (where reached >= {i}) as {k}" for i, k in enumerate(STAGES))
                                   + " from app.prospect_companies where campaign_id = cast(:c as uuid)"), {"c": campaign_id})).mappings().one()
    drops = (await conn.execute(text("""select drop_reason, count(*) as n from app.prospect_companies
        where campaign_id = cast(:c as uuid) and drop_reason is not null group by drop_reason order by n desc"""), {"c": campaign_id})).all()
    reviews = dict((await conn.execute(text("select review, count(*) from app.prospects where campaign_id = cast(:c as uuid) group by review"),
                                       {"c": campaign_id})).all())
    return {"steps": [{"key": k, "label": STAGE_LABELS[k], "count": row[k]} for k in STAGES],
            "dropped": [{"reason": r.drop_reason, "count": r.n} for r in drops],
            "review": {k: reviews.get(k, 0) for k in ("pending", "needs_attention", "approved", "dropped")}}

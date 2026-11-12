"""Self-serve start (docs/PLAN-COMMERCIAL-2026-11.md #1): a visitor buys a plan on the website and gets an account.

    plans      agent packs marked self_serve, with what the first payment is (setup + first month + GST)
    start      website /start: plan, business, website, name, email, phone (+ Turnstile). A Razorpay payment link for the
               first payment (Agentry's own gateway, notes.signup_id). No gateway configured -> a demo request instead.
    paid       the billing webhook (payment_link.paid with notes.signup_id) marks it paid and emails the payer a link to
               their account: proof they own the email. Nothing is created before payment.
    claim      the link opens the portal (apps/dashboard /start/{id}), which makes the organisation and the owner's user
               (Better Auth's tables are the portal's) and claims the sign-up for that organisation, once
    provision  the newly signed-in owner's portal calls /signups/{id}/provision: the plan's agents in setup, the plan's price
               as the billing plan, the website read into the knowledge base, HQ told. They then follow onboarding and go
               live in approval mode like any client.
"""
import asyncio
import hashlib
import json
import logging
import secrets
from decimal import Decimal

from sqlalchemy import text

from agentry import site_audit
from agentry.config import settings
from agentry.connectors.http import client
from agentry.db import system_session, tenant_session
from agentry.secrets import decrypt_json, encrypt_json

log = logging.getLogger(__name__)
PER_VISITOR_PER_DAY = 3
TIMEZONES = {"IN": "Asia/Kolkata", "US": "America/New_York", "GB": "Europe/London", "AE": "Asia/Dubai", "SG": "Asia/Singapore",
             "AU": "Australia/Sydney", "CA": "America/Toronto"}


class SignupError(site_audit.AuditRefused):
    pass


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def first_payment(plan: dict) -> dict:
    setup, month = Decimal(str(plan.get("setup_fee") or 0)), Decimal(str(plan.get("retainer") or 0))
    tax = ((setup + month) * Decimal(str(plan.get("tax_rate") or 0))).quantize(Decimal("0.01"))
    return {"setup": setup, "month": month, "tax": tax, "total": setup + month + tax}


async def plans(currency: str = "INR") -> list[dict]:
    from agentry.automations import REGISTRY
    from agentry.features import FEATURES  # noqa: F401 - names come from the catalogue below
    async with system_session() as conn:
        rows = (await conn.execute(text("""select key, name, tagline, audience, agents, pricing, highlights from app.agent_packs
            where active and self_serve order by sort, name"""))).mappings().all()
    out = []
    for r in rows:
        p = (r["pricing"] or {}).get(currency)
        if not p:
            continue
        pay = first_payment(p)
        out.append({"key": r["key"], "name": r["name"], "tagline": r["tagline"], "audience": r["audience"], "highlights": r["highlights"],
                    "agents": [REGISTRY[a["key"]].name for a in r["agents"] if a.get("default_on") and a["key"] in REGISTRY],
                    "optional": [REGISTRY[a["key"]].name for a in r["agents"] if not a.get("default_on") and a["key"] in REGISTRY],
                    "currency": currency, "monthly": str(pay["month"]), "setup": str(pay["setup"]), "tax_rate": p.get("tax_rate") or 0,
                    "first_payment": str(pay["total"]), "included_messages": (p.get("included") or {}).get("messages")})
    return out


async def _pay_link(signup_id: str, amount: Decimal, currency: str, business: str, name: str, email: str, phone: str | None, pack: str) -> str | None:
    if currency != "INR" or not settings.billing_razorpay_key_id:
        return None
    async with client() as c:
        r = await c.post("https://api.razorpay.com/v1/payment_links", auth=(settings.billing_razorpay_key_id, settings.billing_razorpay_key_secret or ""),
                         json={"amount": int(amount * 100), "currency": "INR", "description": f"{settings.company_name} {pack} plan: first month for {business}"[:250],
                               "customer": {"name": name, "email": email, **({"contact": phone} if phone else {})}, "notify": {"email": False, "sms": False},
                               "reference_id": f"signup-{signup_id[:30]}", "notes": {"signup_id": signup_id, "business": business[:200]},
                               "callback_url": f"{settings.web_url}/start/done/{signup_id}", "callback_method": "get"})
    return r.json().get("short_url") if r.status_code < 300 else None


async def start(*, pack: str, business: str, website: str | None, name: str, email: str, phone: str | None, country: str,
                ip: str | None, source: str | None) -> dict:
    email = email.strip().lower()
    async with system_session() as conn:
        if not await site_audit.hit(conn, f"signup:{site_audit.ip_hash(ip)}", PER_VISITOR_PER_DAY, "24 hours"):
            raise SignupError(429, "too many sign-ups from here today: write to us and we'll set you up")
        p = (await conn.execute(text("select name, pricing from app.agent_packs where key = :k and active and self_serve"), {"k": pack})).mappings().first()
    currency = "INR" if country == "IN" else "USD"
    plan = (p["pricing"] or {}).get(currency) if p else None
    if not plan:
        raise SignupError(422, "that plan isn't available: pick another")
    pay = first_payment(plan)
    token = secrets.token_urlsafe(24)
    async with system_session() as conn:
        sid = str((await conn.execute(text("""insert into app.signups (pack, business, website, name, email, phone, country, currency, amount, token_hash,
            token_enc, source, ip_hash) values (:p, :b, :w, :n, :e, :ph, :c, :cur, :a, :t, :tok, :s, :ip) returning id"""),
            {"p": pack, "b": business.strip()[:120], "w": (website or "").strip()[:200] or None, "n": name.strip()[:120], "e": email, "ph": phone,
             "c": country, "cur": currency, "a": pay["total"], "t": _hash(token), "s": (source or "")[:300] or None, "ip": site_audit.ip_hash(ip),
             "tok": encrypt_json({"t": token})})).scalar_one())
    link = await _pay_link(sid, pay["total"], currency, business, name, email, phone, p["name"])
    if not link:  # no gateway: hand it to a person (a demo request, so the usual follow-ups and HQ alert happen)
        async with system_session() as conn:
            await conn.execute(text("update app.signups set status = 'cancelled', error = 'no payment gateway' where id = cast(:i as uuid)"), {"i": sid})
            did = str((await conn.execute(text("""insert into app.demo_requests (name, email, phone, company, website, niche, message)
                values (:n, :e, :ph, :b, :w, 'other', :m) returning id"""), {"n": name, "e": email, "ph": phone, "b": business, "w": website,
                "m": f"Wants to start on the {p['name']} plan ({currency} {pay['total']} first payment). Online payment isn't switched on: please call and set them up."})).scalar_one())
            from agentry.events import emit
            await emit(conn, None, "demo_request.created", {"demo_request_id": did})
        return {"id": sid, "pay_url": None, "handoff": True}
    async with system_session() as conn:
        await conn.execute(text("update app.signups set payment_link = :l where id = cast(:i as uuid)"), {"l": link, "i": sid})
    return {"id": sid, "pay_url": link, "handoff": False}


def _token_of(row: dict) -> str:
    return decrypt_json(row["token_enc"])["t"]


async def mark_paid(signup_id: str, reference: str) -> bool:
    """From the billing webhook. Emails the account link once. True when this call marked it paid."""
    async with system_session() as conn:
        row = (await conn.execute(text("""update app.signups set status = 'paid', paid_at = now()
            where id = cast(:i as uuid) and status = 'pending_payment' returning *"""), {"i": signup_id})).mappings().first()
        if not row:
            return False
        token = _token_of(dict(row))
        await conn.execute(text("update app.signups set payment_ref = :r where id = cast(:i as uuid)"), {"r": reference[:100], "i": signup_id})
        from agentry.events import emit
        await emit(conn, None, "signup.paid", {"signup_id": signup_id})
    link = f"{settings.dashboard_url}/start/{signup_id}?k={token}"
    from agentry.notify.email import send_email
    body = (f"Hi {row['name'].split()[0]},\n\nThank you: your payment for {settings.company_name} is in.\n\nOpen your account here (one click signs you "
            f"in; it also confirms this is your email):\n{link}\n\nYou'll set up {row['business']} in a few steps: your WhatsApp number, your "
            "services and prices, and a test conversation. Your assistant starts in approval mode, so you see every reply before it goes.\n\n"
            "Reply to this email if you need a hand.\n")
    try:
        await asyncio.to_thread(send_email, row["email"], f"Your {settings.company_name} account is ready to open", body)
        await asyncio.to_thread(send_email, settings.ops_email, f"New self-serve customer: {row['business']} ({row['pack']}, {row['currency']} {row['amount']})",
                                f"{row['name']} <{row['email']}> {row['phone'] or ''} paid {row['currency']} {row['amount']} for the {row['pack']} plan.\n"
                                f"Website: {row['website'] or '-'}\nThey get the account link by email; HQ shows the client once they open it.")
    except Exception as e:  # noqa: BLE001 - the sign-up is paid either way; HQ can resend the link
        log.warning("couldn't email the account link for sign-up %s: %s", signup_id, e)
    return True


async def resend(signup_id: str) -> None:
    """HQ: send the account link again (a paid sign-up not opened yet)."""
    async with system_session() as conn:
        row = (await conn.execute(text("select * from app.signups where id = cast(:i as uuid) and status = 'paid'"), {"i": signup_id})).mappings().first()
    if not row:
        raise SignupError(404, "no paid sign-up waiting to be opened")
    from agentry.notify.email import send_email
    await asyncio.to_thread(send_email, row["email"], f"Your {settings.company_name} account link",
                            f"Open your account here:\n{settings.dashboard_url}/start/{signup_id}?k={_token_of(dict(row))}\n")


async def _row(signup_id: str, token: str) -> dict:
    async with system_session() as conn:
        row = (await conn.execute(text("select *, id::text as id from app.signups where id = cast(:i as uuid)"), {"i": signup_id})).mappings().first()
    if not row or not secrets.compare_digest(row["token_hash"], _hash(token or "")):
        raise SignupError(404, "this link isn't valid")
    return dict(row)


async def status(signup_id: str, token: str | None = None) -> dict:
    """The website's done page (no token: only the status) and the portal (with the token: what it needs to make the account)."""
    if token:
        r = await _row(signup_id, token)
        return {"status": r["status"], "business": r["business"], "name": r["name"], "email": r["email"], "org_id": r["org_id"], "pack": r["pack"]}
    async with system_session() as conn:
        r = (await conn.execute(text("select status, business, email from app.signups where id = cast(:i as uuid)"), {"i": signup_id})).mappings().first()
    if not r:
        raise SignupError(404, "not found")
    e = r["email"]
    return {"status": r["status"], "business": r["business"], "email": e[0] + "•••" + e[e.index("@"):]}


async def claim(signup_id: str, token: str, org_id: str) -> bool:
    """The portal made the organisation: record it, once. False when another click already did (the portal then deletes its copy)."""
    await _row(signup_id, token)
    async with system_session() as conn:
        return bool((await conn.execute(text("""update app.signups set org_id = :o, status = 'claimed'
            where id = cast(:i as uuid) and status = 'paid' and org_id is null"""), {"o": org_id, "i": signup_id})).rowcount)


async def provision(signup_id: str, token: str, *, org_id: str, user_email: str) -> dict:
    """Called by the signed-in owner's portal right after the claim."""
    from agentry import billing, clients
    r = await _row(signup_id, token)
    if r["status"] == "provisioned" and r["org_id"] == org_id:
        return {"status": "provisioned", "org_id": org_id}
    if r["status"] != "claimed" or r["org_id"] != org_id:
        raise SignupError(409, "this sign-up isn't ready to set up")
    if r["email"] != (user_email or "").strip().lower():
        raise SignupError(403, "sign in with the email you paid with")
    async with system_session() as conn:
        pricing = (await conn.execute(text("select pricing from app.agent_packs where key = :k"), {"k": r["pack"]})).scalar_one()
    from calendar import monthrange
    from datetime import UTC, date, datetime
    today = datetime.now(UTC).date()
    # the first payment covered this month: this month's statement doesn't charge the retainer again
    plan = billing.PricingPlan(**pricing[r["currency"]], pilot_until=date(today.year, today.month, monthrange(today.year, today.month)[1]))
    try:
        async with tenant_session(org_id) as conn:
            await clients.provision(conn, org_id, name=r["business"], country=r["country"], timezone=TIMEZONES.get(r["country"], "Asia/Kolkata"),
                                    currency=r["currency"], website=r["website"], automations=[], plan=plan, staff_user_id="self-serve", pack=r["pack"])
            # the first payment covers the setup fee and the first month: the first statement shouldn't bill them again
            await conn.execute(text("update app.pricing_plans set setup_billed = true where org_id = :o"), {"o": org_id})
            # the plan is chosen and paid for: that onboarding step is done
            await conn.execute(text("update app.onboarding_progress set status = 'done' where step_key = 'plan'"))
    except clients.ProvisionError as e:
        async with system_session() as conn:
            await conn.execute(text("update app.signups set status = 'failed', error = :e where id = cast(:i as uuid)"), {"e": str(e)[:300], "i": signup_id})
        raise SignupError(409, str(e)) from e
    async with system_session() as conn:
        await conn.execute(text("update app.signups set status = 'provisioned', provisioned_at = now() where id = cast(:i as uuid)"), {"i": signup_id})
        from agentry.events import emit
        await emit(conn, org_id, "signup.provisioned", {"signup_id": signup_id, "website": r["website"]})
    return {"status": "provisioned", "org_id": org_id}


async def learn_website(org_id: str, website: str | None) -> int:
    """After provisioning (worker): the website read into the knowledge base, so the assistant can answer on day one."""
    if not website:
        return 0
    from agentry.knowledge import add_document, crawl
    try:
        pages = await crawl(website if "://" in website else f"https://{website}", max_pages=8)
    except Exception:  # noqa: BLE001 - an unreadable site just means they add their facts by hand in onboarding
        return 0
    n = 0
    for p in pages:
        if len(p.text) > 80:
            await add_document(org_id, source_type="url", title=p.title or p.url, content=p.text, source_ref=p.url)
            n += 1
    if n:
        async with tenant_session(org_id) as conn:
            await conn.execute(text("""update app.onboarding_progress set status = 'done' where step_key = 'knowledge'"""))
    return n


async def listing() -> list[dict]:
    async with system_session() as conn:
        rows = (await conn.execute(text("""select id::text, pack, business, website, name, email, phone, currency, amount, status, org_id, error,
            created_at, paid_at, provisioned_at from app.signups where status <> 'pending_payment' or created_at > now() - interval '7 days'
            order by created_at desc limit 100"""))).mappings().all()
    return [json.loads(json.dumps(dict(r), default=str)) for r in rows]

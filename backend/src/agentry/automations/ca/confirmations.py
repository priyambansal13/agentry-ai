"""Balance confirmations (CA desk part 2, docs/PLAN-CA-DESK-2.md #7): a client's debtor and creditor balances -> a request
to each party to confirm the balance directly to the auditor (SA 505), replies tracked, and a summary for the audit file.

    read       the balances sheet through the Excel cleaner: party, group / type (debtor or creditor; else Dr = debtor,
               Cr = creditor), balance (or Debit / Credit columns), email
    select     every party at or above a minimum balance (the rest marked "not selected"); parties without an email are
               listed to send by hand
    draft      one request per party: the client's balance with them as at the date, a private link to agree or give their
               own figure (and attach their statement), or reply to the email
    send       only when the CA presses Send: from the firm's connected mailbox (Gmail / Outlook); without one, or to a
               test address, the request is recorded and the text is there to send by hand. A reminder adds a new link;
               the old ones keep working until they expire (60 days)
    replies    on the link: agreed, or differs with their figure and a note (and their statement, filed on the client) ·
               an email reply pasted in: read by rules (confirm / agree with no other figure, or "our books show ₹x"),
               the AI only when the rules can't tell, and a figure the AI gives must be in the reply · or set by hand
    summary    by debtors / creditors: balances, selected, sent, agreed, differs (with the difference), no reply,
               coverage of the total, and the follow-up each needs (alternative procedures for no reply: receipts after
               the year end, invoices, GRNs)
The batch is a piece of work (agent "ca_balance_confirmations"); its result is rebuilt from the party rows after every
change, so the page and the Excel always show the latest.
"""
import hashlib
import json
import re
import secrets
from datetime import UTC, date, datetime

from sqlalchemy import text

from agentry import audit, site_audit
from agentry.automations.ca import cleaner, core
from agentry.config import settings
from agentry.db import system_session, tenant_session
from agentry.llm.gateway import AllModelsFailed, complete
from agentry.llm.prompts import load
from agentry.notify.email import RESERVED

AGENT = "ca_balance_confirmations"
LINK_DAYS = 60
REMIND_AFTER = 7  # days since the last request before a reminder is offered
AGREE = re.compile(r"\b(confirm(ed|s)?|agree[ds]?|correct|in order|tall(y|ies|ied)|match(es|ed)?|reconciled|accepted)\b", re.IGNORECASE)
DISAGREE = re.compile(r"\b(not|don'?t|doesn'?t|do not|does not|cannot|can'?t|un)\s*(agree|confirm|correct|match|tally|reconcile)|disagree|differ|"
                      r"mismatch|discrepan|instead|whereas|however|as per our (books|records|ledger|accounts)|our (books|records|ledger|accounts) (show|reflect)",
                      re.IGNORECASE)
THEIRS = re.compile(r"(as per our (books|records|ledger|accounts?)|our (books|records|ledger|accounts?)( of accounts?)?\s*(shows?|reflects?|says?)?|"
                    r"balance (payable|receivable|due|outstanding)\b[^.]{0,80}?\bis\b|in our books)", re.IGNORECASE)
AMOUNT = re.compile(r"(?:₹|rs\.?|inr)?\s*(\d{1,3}(?:,\d{2,3})+(?:\.\d{1,2})?|\d{4,}(?:\.\d{1,2})?)", re.IGNORECASE)


class ConfirmError(site_audit.AuditRefused):
    pass


def _hash(t: str) -> str:
    return hashlib.sha256(t.encode()).hexdigest()


def url_for(token: str) -> str:
    return f"{settings.web_url.rstrip('/')}/confirm/{token}"


def _f(v: object) -> float:
    if isinstance(v, (int, float)):
        return float(v)
    return (cleaner._num(v) or 0.0) if isinstance(v, str) and v.strip() else 0.0


# ---------- the balances sheet ----------

def read(rows: list[list[str]]) -> tuple[list[dict], dict]:
    """(parties [{party, kind, balance (debit +), email}], columns used)."""
    c = cleaner.clean(rows, drop_duplicates=False)
    cols, kinds, data = c["columns"], c["kinds"], c["rows"]
    lc = [x.lower() for x in cols]

    def col(rx: str, kind: str | None = None, avoid: str | None = None) -> int | None:
        return next((j for j, x in enumerate(lc) if re.search(rx, x) and (kind is None or kinds[j] == kind) and not (avoid and re.search(avoid, x))), None)
    k = {"party": col(r"party|name|ledger|particulars|customer|supplier|vendor|account", "text", r"group|type|email|mail"),
         "group": col(r"group|type|under|category|nature|debtor|creditor"),
         "email": next((j for j, x in enumerate(lc) if re.search(r"e-?mail|mail id", x)), None),
         "debit": col(r"\bdebit\b|\bdr\b", "number"), "credit": col(r"\bcredit\b|\bcr\b", "number"),
         "balance": col(r"balance|amount|closing|outstanding|due", "number")}
    if k["party"] is None or (k["balance"] is None and k["debit"] is None):
        raise core.CaError("this needs a party column and a balance (or Debit / Credit) column")
    out = []
    for r in data:
        name = str(r[k["party"]] or "").strip()
        if not name or cleaner.TOTAL.match(name):
            continue
        bal = (_f(r[k["debit"]]) - (_f(r[k["credit"]]) if k["credit"] is not None else 0.0)) if k["debit"] is not None else _f(r[k["balance"]])
        if not bal:
            continue
        grp = str(r[k["group"]] or "").lower() if k["group"] is not None else ""
        kind = "debtor" if re.search(r"debtor|customer|receivable|buyer|client", grp) else \
               "creditor" if re.search(r"creditor|supplier|payable|vendor", grp) else ("debtor" if bal > 0 else "creditor")
        email = str(r[k["email"]] or "").strip().lower() if k["email"] is not None else ""
        out.append({"party": name[:200], "kind": kind, "balance": round(bal, 2),
                    "email": email if re.fullmatch(r"[^@\s,;]+@[^@\s,;]+\.[a-z]{2,}", email) else None})
    if not out:
        raise core.CaError("no balances found")
    return out, {key: cols[j] for key, j in k.items() if j is not None}


def select(parties: list[dict], min_balance: float = 0.0) -> list[dict]:
    """Status per party: draft (to send), no_email, not_selected (below the minimum)."""
    for p in parties:
        p["status"] = "not_selected" if abs(p["balance"]) < min_balance else ("draft" if p.get("email") else "no_email")
    return parties


def inr(v: float) -> str:
    """₹4,85,600.00: Indian digit grouping."""
    whole, paise = f"{abs(v):.2f}".split(".")
    head, tail = whole[:-3], whole[-3:]
    head = ",".join(re.findall(r"\d{1,2}", head[::-1]))[::-1] if head else ""
    return f"₹{head + ',' if head else ''}{tail}.{paise}"


def _side(p: dict) -> str:
    """The balance in words, from the party's side."""
    amt = inr(p["balance"])
    if p["kind"] == "debtor":
        return f"{amt} receivable from you" if p["balance"] > 0 else f"{amt} payable to you (an advance from you)"
    return f"{amt} payable to you" if p["balance"] < 0 else f"{amt} receivable from you (an advance to you)"


def draft(p: dict, *, firm: str, client: str, as_of: str, url: str | None, reminder: bool = False) -> tuple[str, str]:
    """(subject, body) of the request."""
    when = date.fromisoformat(as_of).strftime("%d %b %Y")
    subject = f"{'Reminder: ' if reminder else ''}Balance confirmation as at {when}: {client}"
    body = (f"Dear Sir / Madam,\n\n"
            f"{'We wrote to you earlier and have not yet heard back. ' if reminder else ''}"
            f"As part of the audit of {client}'s accounts, please confirm your account balance with them as at {when}.\n\n"
            f"As per {client}'s books: {_side(p)}.\n\n"
            + (f"Please confirm directly to us, the auditors, here (it takes a minute: agree, or give your figure and attach your "
               f"statement of account):\n{url}\n\n" if url else "")
            + "Or reply to this email. If the balance doesn't match, please give the balance in your books and send your statement "
              "of account for the year, so the difference can be reconciled.\n\n"
              f"This is a request for information only, not a demand for payment.\n\nThank you,\n{firm}\n(auditors of {client})")
    return subject, body


# ---------- reading a reply ----------

def amounts(reply: str) -> list[float]:
    out = []
    for m in AMOUNT.finditer(reply or ""):
        try:
            v = float(m[1].replace(",", ""))
        except ValueError:
            continue
        if not (1900 <= v <= 2100 and "," not in m[1] and "." not in m[1]):  # not a year
            out.append(v)
    return out


def read_rules(reply: str, our: float) -> dict | None:
    """{status, their_balance} when the rules can tell, else None."""
    t = (reply or "").strip()
    if not t:
        return None
    ours = round(abs(our), 2)
    nums = amounts(t)
    others = [n for n in nums if abs(n - ours) > 1]
    if DISAGREE.search(t):
        if m := THEIRS.search(t):  # the figure that follows "as per our books" / "our ledger shows"
            after = amounts(t[m.end():m.end() + 160])
            if after and abs(after[0] - ours) > 1:
                return {"status": "differs", "their_balance": after[0]}
        if len(set(others)) == 1:
            return {"status": "differs", "their_balance": others[0]}
        if not nums and re.search(r"\b(nil|zero|no balance|nothing (is )?due|fully (paid|settled))\b", t, re.IGNORECASE):
            return {"status": "differs", "their_balance": 0.0}
        return None
    if AGREE.search(t) and not others:
        return {"status": "agreed", "their_balance": ours}
    return None


async def read_reply(org_id: str | None, reply: str, p: dict, use_model: bool = True) -> dict:
    """{status (agreed / differs / unclear), their_balance, read_by, note}."""
    if r := read_rules(reply, p["our_balance"]):
        return r | {"read_by": "rules", "note": None}
    if not use_model:
        return {"status": "unclear", "their_balance": None, "read_by": "rules", "note": "the rules couldn't tell: read it and set the result"}
    prompt = load("ca_confirmation_reply")
    msgs = prompt.render(party=p["party"], client=p.get("client") or "the client", balance=f"{abs(float(p['our_balance'])):,.2f}",
                         side=_side({"kind": p["kind"], "balance": float(p["our_balance"])}), reply=reply[:4000])
    try:
        res = await complete(prompt.tier, msgs, org_id=org_id, prompt_key=prompt.key, prompt_version=prompt.version, json_output=True,
                             mock_response=json.dumps({"status": "unclear", "their_balance": None, "why": "test mode"}), temperature=0)
        got = res.data if isinstance(res.data, dict) else {}
    except AllModelsFailed:
        got = {}
    status = got.get("status") if got.get("status") in ("agreed", "differs", "unclear") else "unclear"
    bal = got.get("their_balance")
    try:
        bal = float(bal) if bal is not None else None
    except (TypeError, ValueError):
        bal = None
    if status == "differs" and (bal is None or not any(abs(bal - n) < 1 for n in amounts(reply))) and bal != 0:
        status, bal = "unclear", None  # a figure that isn't in the reply is never taken
    if status == "agreed":
        bal = round(abs(float(p["our_balance"])), 2)
    return {"status": status, "their_balance": bal, "read_by": "ai", "note": str(got.get("why") or "")[:200] or None}


# ---------- the summary (also the website box) ----------

def summarise(parties: list[dict]) -> dict:
    """parties: {kind, our_balance (debit +), status, their_balance, replied_at?}."""
    out = {}
    for kind in ("debtor", "creditor"):
        ps = [p for p in parties if p["kind"] == kind]
        amt = lambda xs: round(sum(abs(float(x["our_balance"])) for x in xs), 2)
        asked = [p for p in ps if p["status"] in ("sent", "agreed", "differs", "unclear")]
        agreed = [p for p in ps if p["status"] == "agreed"]
        differs = [p for p in ps if p["status"] == "differs"]
        waiting = [p for p in ps if p["status"] == "sent"]
        total = amt(ps)
        out[kind] = {"parties": len(ps), "balance": total, "selected": sum(1 for p in ps if p["status"] != "not_selected"),
                     "selected_amount": amt([p for p in ps if p["status"] != "not_selected"]),
                     "no_email": sum(1 for p in ps if p["status"] == "no_email"), "drafts": sum(1 for p in ps if p["status"] == "draft"),
                     "sent": len(asked), "sent_amount": amt(asked), "agreed": len(agreed), "agreed_amount": amt(agreed),
                     "differs": len(differs), "difference": round(sum(abs(float(p["our_balance"])) - float(p["their_balance"] or 0) for p in differs), 2),
                     "unclear": sum(1 for p in ps if p["status"] == "unclear"), "no_reply": len(waiting), "no_reply_amount": amt(waiting),
                     "coverage_pct": round(amt(agreed) / total * 100, 1) if total else 0.0,
                     "response_pct": round((len(asked) - len(waiting)) / len(asked) * 100, 1) if asked else 0.0}
    return out


FOLLOW_UP = {"agreed": "None: confirmed.", "differs": "Reconcile: get the party's statement, list invoices / payments / credit notes in transit.",
             "sent": "Remind; if still no reply, alternative procedures: receipts / payments after the year end, invoices, delivery notes / GRNs.",
             "unclear": "Read the reply and set the result.", "no_email": "Get an email address, or send the letter by post / hand.",
             "draft": "Send the request.", "not_selected": "Below the minimum balance chosen: not asked."}


# ---------- the batch ----------

async def _firm(conn) -> str:
    return (await conn.execute(text("select o.name from auth.organization o join app.org_settings s on s.org_id = o.id"))).scalar_one_or_none() or "Your auditors"


async def refresh(conn, wid: str) -> dict:
    """The work's result rebuilt from the party rows."""
    w = (await conn.execute(text("select result from app.ca_work where id = cast(:w as uuid)"), {"w": wid})).mappings().one()
    rows = (await conn.execute(text("""select id::text, party, kind, email, our_balance::float as our_balance, as_of, status, sent_at, sent_via, reminders,
        last_sent_at, replied_at, reply_via, their_balance::float as their_balance, reply_note, reply_read_by, reply_file_id::text
        from app.ca_confirmations where work_id = cast(:w as uuid) order by kind, abs(our_balance) desc"""), {"w": wid})).mappings().all()
    now = datetime.now(UTC)
    parties = []
    for r in rows:
        p = dict(r)
        p["difference"] = round(abs(p["our_balance"]) - p["their_balance"], 2) if p["status"] == "differs" and p["their_balance"] is not None else None
        p["remind"] = p["status"] == "sent" and p["last_sent_at"] is not None and (now - p["last_sent_at"]).days >= REMIND_AFTER
        p["follow_up"] = FOLLOW_UP[p["status"]]
        parties.append(p)
    result = {**w["result"], "parties": parties, "summary": summarise(parties)}
    await conn.execute(text("update app.ca_work set result = cast(:r as jsonb), updated_at = now() where id = cast(:w as uuid)"),
                       {"r": json.dumps(result, default=str), "w": wid})
    return result


async def prepare(org_id: str, client_id: str, data: bytes, mime: str, *, as_of: str, min_balance: float = 0.0, user_id: str | None = None,
                  file_id: str | None = None, title: str | None = None) -> dict:
    if not (mime.endswith("spreadsheetml.sheet") or mime in ("text/csv", "text/plain", "application/vnd.ms-excel")):
        raise core.CaError("balance confirmations work on a list of debtor / creditor balances in CSV or Excel (.xlsx)")
    try:
        d = date.fromisoformat(as_of)
    except ValueError as e:
        raise core.CaError("the date as YYYY-MM-DD") from e
    parties, used = read(core.table_rows(data, mime))
    select(parties, min_balance)
    async with tenant_session(org_id) as conn:
        c = (await conn.execute(text("select name from app.ca_clients where id = cast(:c as uuid)"), {"c": client_id})).scalar_one()
        firm = await _firm(conn)
        result = {"client": c, "firm": firm, "as_of": d.isoformat(), "min_balance": min_balance, "columns": used}
        wid = await core.save_work(conn, org_id, client_id, AGENT, title or f"Balance confirmations as at {d:%d %b %Y}", result,
                                   file_ids=[file_id] if file_id else [], params={"as_of": d.isoformat(), "min_balance": min_balance}, user_id=user_id)
        for p in parties:
            await conn.execute(text("""insert into app.ca_confirmations (org_id, client_id, work_id, party, kind, email, our_balance, as_of, status)
                values (:o, cast(:c as uuid), cast(:w as uuid), :p, :k, :e, :b, :d, :s)"""),
                {"o": org_id, "c": client_id, "w": wid, "p": p["party"], "k": p["kind"], "e": p["email"], "b": p["balance"], "d": d, "s": p["status"]})
        r = await refresh(conn, wid)
    return {"id": wid, "result": r}


async def _mail(conn, org_id: str, to: str, subject: str, body: str) -> str:
    """Sent from the firm's mailbox; 'recorded' when there's none or the address is a test one (never emailed)."""
    from agentry.outbound import _sending_mailbox
    if to.lower().endswith(RESERVED):
        return "recorded"
    box = await _sending_mailbox(conn, org_id, AGENT)
    if box and box["provider"] == "gmail":
        from agentry.connectors.gmail import Gmail
        await Gmail(org_id, box).send_new(to=to, subject=subject, body=body)
        return "gmail"
    if box and box["provider"] == "outlook":
        from agentry.connectors.outlook import Outlook
        await Outlook(org_id, box).send_new(to=to, subject=subject, body=body)
        return "outlook"
    return "recorded"


async def send(org_id: str, wid: str, *, user_id: str | None, reminder: bool = False, ids: list[str] | None = None) -> dict:
    """Send the drafts (or reminders to those who haven't replied after REMIND_AFTER days). Each gets a fresh private link."""
    sent, failed, out = 0, [], []
    async with tenant_session(org_id) as conn:
        w = (await conn.execute(text("select result from app.ca_work where id = cast(:w as uuid) and agent = :a"), {"w": wid, "a": AGENT})).scalar_one_or_none()
        if w is None:
            raise ConfirmError(404, "not a balance confirmation batch")
        if reminder:
            todo = (await conn.execute(text(f"""select * from app.ca_confirmations where work_id = cast(:w as uuid) and status = 'sent'
                and last_sent_at < now() - interval '{REMIND_AFTER} days'"""), {"w": wid})).mappings().all()
        else:
            todo = (await conn.execute(text("select * from app.ca_confirmations where work_id = cast(:w as uuid) and status = 'draft'"), {"w": wid})).mappings().all()
        if ids is not None:
            todo = [t for t in todo if str(t["id"]) in ids]
        for t in todo:
            token = secrets.token_urlsafe(24)
            p = {"party": t["party"], "kind": t["kind"], "balance": float(t["our_balance"])}
            subject, body = draft(p, firm=w["firm"], client=w["client"], as_of=w["as_of"], url=url_for(token), reminder=reminder)
            try:
                via = await _mail(conn, org_id, t["email"], subject, body)
            except Exception as e:  # noqa: BLE001 - one bad address or mailbox error must not stop the rest
                failed.append({"party": t["party"], "why": str(e)[:200]})
                continue
            await conn.execute(text("""update app.ca_confirmations set token_hashes = token_hashes || array[:h], expires_at = now() + make_interval(days => :d),
                status = 'sent', sent_at = coalesce(sent_at, now()), last_sent_at = now(), sent_via = :v, reminders = reminders + :r where id = :i"""),
                {"h": _hash(token), "d": LINK_DAYS, "v": via, "r": 1 if reminder else 0, "i": t["id"]})
            sent += 1
            out.append({"party": t["party"], "via": via, **({"subject": subject, "body": body} if via == "recorded" else {})})
        await refresh(conn, wid)
        await audit.record(conn, org_id=org_id, actor_type="user", actor_user_id=user_id, action=f"{AGENT}.{'remind' if reminder else 'send'}",
                           target_type="ca_work", target_id=wid, metadata={"sent": sent, "failed": len(failed)})
    return {"sent": sent, "failed": failed, "messages": out}


async def _party(conn, wid: str, pid: str) -> dict:
    p = (await conn.execute(text("""select c.*, w.result->>'client' as client from app.ca_confirmations c join app.ca_work w on w.id = c.work_id
        where c.id = cast(:p as uuid) and c.work_id = cast(:w as uuid)"""), {"p": pid, "w": wid})).mappings().first()
    if not p:
        raise ConfirmError(404, "party not found")
    return dict(p)


async def _set_reply(conn, pid: str, status: str, their: float | None, via: str, note: str | None, read_by: str, file_id: str | None = None) -> None:
    await conn.execute(text("""update app.ca_confirmations set status = :s, their_balance = :b, reply_via = :v, reply_note = :n, reply_read_by = :r,
        replied_at = now(), reply_file_id = coalesce(cast(:f as uuid), reply_file_id) where id = cast(:i as uuid)"""),
        {"s": status, "b": their, "v": via, "n": (note or "")[:2000] or None, "r": read_by, "f": file_id, "i": pid})


async def record_reply(org_id: str, wid: str, pid: str, reply: str, *, user_id: str | None, use_model: bool = True) -> dict:
    """An email reply pasted in by staff: read (rules, then the AI), recorded with the reply's text."""
    async with tenant_session(org_id) as conn:
        p = await _party(conn, wid, pid)
        p["our_balance"] = float(p["our_balance"])
    got = await read_reply(org_id, reply, p, use_model)
    async with tenant_session(org_id) as conn:
        await _set_reply(conn, pid, got["status"], got["their_balance"], "email", reply, got["read_by"])
        await refresh(conn, wid)
        await audit.record(conn, org_id=org_id, actor_type="user", actor_user_id=user_id, action=f"{AGENT}.reply", target_type="ca_confirmation",
                           target_id=pid, metadata={"status": got["status"], "read_by": got["read_by"]})
    return got


async def set_result(org_id: str, wid: str, pid: str, *, status: str, their_balance: float | None, note: str | None, user_id: str | None,
                     email: str | None = None) -> dict:
    """Staff set the result by hand (a letter came back, a phone call), or add / fix an email (a no-email party becomes a draft)."""
    async with tenant_session(org_id) as conn:
        p = await _party(conn, wid, pid)
        if email is not None:
            if not re.fullmatch(r"[^@\s,;]+@[^@\s,;]+\.[a-z]{2,}", email.strip().lower()):
                raise ConfirmError(422, "that doesn't look like an email address")
            await conn.execute(text("""update app.ca_confirmations set email = :e, status = case when status in ('no_email','not_selected') then 'draft' else status end
                where id = cast(:i as uuid)"""), {"e": email.strip().lower(), "i": pid})
        if status:
            if status not in ("agreed", "differs", "unclear"):
                raise ConfirmError(422, "agreed, differs or unclear")
            if status == "differs" and their_balance is None:
                raise ConfirmError(422, "give the party's figure")
            their = round(abs(float(p["our_balance"])), 2) if status == "agreed" else their_balance
            await _set_reply(conn, pid, status, their, "manual", note, "staff")
        r = await refresh(conn, wid)
        await audit.record(conn, org_id=org_id, actor_type="user", actor_user_id=user_id, action=f"{AGENT}.set", target_type="ca_confirmation",
                           target_id=pid, metadata={"status": status, "email_changed": email is not None})
    return {"summary": r["summary"]}


# ---------- the party's page (public, by private link) ----------

async def _resolve(token: str) -> tuple[str, dict]:
    async with system_session() as conn:
        r = (await conn.execute(text("""select org_id, id::text from app.ca_confirmations where :h = any(token_hashes) and expires_at > now()"""),
                                {"h": _hash(token or "")})).first()
    if not r:
        raise ConfirmError(404, "this link has expired: please reply to the email instead")
    async with tenant_session(r.org_id) as conn:
        p = (await conn.execute(text("""select c.*, w.result->>'client' as client, w.result->>'firm' as firm from app.ca_confirmations c
            join app.ca_work w on w.id = c.work_id where c.id = cast(:i as uuid)"""), {"i": r.id})).mappings().one()
    return r.org_id, dict(p)


async def view(token: str) -> dict:
    _org, p = await _resolve(token)
    return {"firm": p["firm"], "client": p["client"], "party": p["party"], "as_of": p["as_of"], "kind": p["kind"],
            "balance": abs(float(p["our_balance"])), "side": _side({"kind": p["kind"], "balance": float(p["our_balance"])}),
            "answered": p["reply_via"] == "link" and p["status"] in ("agreed", "differs"),
            "answer": {"status": p["status"], "their_balance": float(p["their_balance"]) if p["their_balance"] is not None else None}
            if p["reply_via"] == "link" else None}


async def respond(token: str, *, agree: bool, their_balance: float | None, note: str | None, file: tuple[bytes, str | None, str | None] | None,
                  ip: str | None) -> dict:
    org_id, p = await _resolve(token)
    async with system_session() as conn:
        if not await site_audit.hit(conn, f"confirm:{p['id']}", 10, "24 hours") or not await site_audit.hit(conn, f"confirm-ip:{site_audit.ip_hash(ip)}", 60, "1 hour"):
            raise ConfirmError(429, "too many tries: please reply to the email instead")
    if not agree and their_balance is None:
        raise ConfirmError(422, "give the balance in your books")
    if their_balance is not None and not (0 <= their_balance < 1e13):
        raise ConfirmError(422, "the balance as a positive amount")
    async with tenant_session(org_id) as conn:
        fid = None
        if file and file[0]:
            try:
                fid = await core.store_file(conn, org_id, str(p["client_id"]), file[0], filename=file[1], mime=file[2], source="confirmation",
                                            doc_type="balance_confirmation")
            except core.CaError as e:
                raise ConfirmError(422, str(e)) from e
        ours = round(abs(float(p["our_balance"])), 2)
        status = "agreed" if agree or (their_balance is not None and abs(their_balance - ours) <= 1) else "differs"
        await _set_reply(conn, p["id"], status, ours if status == "agreed" else their_balance, "link", note, "party", fid)
        await refresh(conn, str(p["work_id"]))
        await audit.record(conn, org_id=org_id, actor_type="system", action=f"{AGENT}.party_replied", target_type="ca_confirmation",
                           target_id=p["id"], metadata={"status": status, "file": bool(fid)})
    return {"status": status}


# ---------- Excel for the audit file ----------

def sheet(result: dict) -> bytes:
    s = result["summary"]
    label = {"draft": "Not sent yet", "not_selected": "Not selected", "no_email": "No email", "sent": "No reply yet", "agreed": "Agreed",
             "differs": "Differs", "unclear": "Reply to read"}
    rows = [["", "Debtors", "Creditors"]]
    for key, name in (("parties", "Parties"), ("balance", "Total balance"), ("selected", "Selected"), ("sent", "Requests sent"),
                      ("sent_amount", "Amount requested"), ("agreed", "Agreed"), ("agreed_amount", "Amount agreed"), ("differs", "Differ"),
                      ("difference", "Total difference (ours - theirs)"), ("no_reply", "No reply"), ("no_reply_amount", "Amount with no reply"),
                      ("no_email", "No email"), ("coverage_pct", "Coverage: agreed / total (%)"), ("response_pct", "Response rate (%)")):
        rows.append([name, s["debtor"][key], s["creditor"][key]])
    return core.xlsx_bytes({
        "Summary": [[f"Balance confirmations: {result['client']} as at {result['as_of']}"], [], *rows],
        "Parties": [["Party", "Debtor / creditor", "Email", "Balance in books (Dr +)", "Status", "Sent", "Reminders", "Replied", "Reply by",
                     "Party's balance", "Difference", "Note", "Follow-up"],
                    *[[p["party"], p["kind"], p["email"] or "", p["our_balance"], label[p["status"]], str(p["sent_at"] or "")[:10], p["reminders"],
                       str(p["replied_at"] or "")[:10], p["reply_via"] or "", p["their_balance"] if p["their_balance"] is not None else "",
                       p["difference"] if p["difference"] is not None else "", (p["reply_note"] or "")[:500], p["follow_up"]] for p in result["parties"]]],
        "To reconcile": [["Party", "Debtor / creditor", "Our balance", "Their balance", "Difference", "Note"],
                         *[[p["party"], p["kind"], abs(p["our_balance"]), p["their_balance"], p["difference"], (p["reply_note"] or "")[:500]]
                           for p in result["parties"] if p["status"] == "differs"]],
    })


def demo(rows: list[list[str]], replies: dict[str, str], *, client: str, firm: str, as_of: str, min_balance: float = 0.0) -> dict:
    """The website box: drafts, the sample replies read by rules, and the summary (nothing stored, nothing sent)."""
    parties, used = read(rows)
    select(parties, min_balance)
    out = []
    for p in parties:
        q = {"party": p["party"], "kind": p["kind"], "email": p["email"], "our_balance": p["balance"], "status": p["status"], "their_balance": None,
             "reply": None, "difference": None}
        if p["status"] == "draft":
            q["status"] = "sent"
            if rep := replies.get(p["party"]):
                got = read_rules(rep, p["balance"]) or {"status": "unclear", "their_balance": None}
                q |= {"reply": rep, **got}
                if got["status"] == "differs":
                    q["difference"] = round(abs(p["balance"]) - got["their_balance"], 2)
        q["follow_up"] = FOLLOW_UP[q["status"]]
        out.append(q)
    first = next((p for p in parties if p["status"] == "draft"), None)
    email = draft(first, firm=firm, client=client, as_of=as_of, url=url_for("…")) if first else None
    return {"parties": out, "summary": summarise(out), "email": {"subject": email[0], "body": email[1]} if email else None, "columns": used,
            "as_of": as_of, "client": client}

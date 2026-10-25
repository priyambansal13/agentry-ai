"""Fixed rules that run before (or instead of) the model.

`rule_decision` returns a final decision for cases rules handle with certainty (payment receipts, obvious phishing),
saving a model call. `heuristic_triage` is a keyword classifier used in mock mode and as the fallback when every
model fails, so triage keeps working (less accurately) through a provider outage.
"""
import re

_LOOKALIKE = re.compile(r"(g00gle|paypa1|micr0soft|amaz0n|faceb00k|app1e)", re.IGNORECASE)
_PHISH = re.compile(r"verify (your )?(password|account)|account will be suspended|confirm your login", re.IGNORECASE)
_PRIZE = re.compile(r"you (have )?won|lottery|claim (your )?prize|bank details to claim", re.IGNORECASE)
_RECEIPT_SENDER = re.compile(r"^(no-?reply|notifications?|billing)@.*(razorpay|stripe|paypal|cashfree|paytm)", re.IGNORECASE)
_URGENT = re.compile(r"\b(asap|urgent|immediately|down|outage|502|500 error|not working|stopped|legal|notice|"
                     r"infringement|lawsuit|deadline today|within 48 hours|losing)\b", re.IGNORECASE)
_INVOICE = re.compile(r"\b(invoice|payment|paid|pay|outstanding|overdue|remittance|receipt|utr|neft|dues)\b", re.IGNORECASE)
_LEAD = re.compile(r"\b(quote|quotation|looking for|need (a|an)|interested in|pricing|proposal|can we talk|"
                   r"budget|hire|enquiry|inquiry)\b", re.IGNORECASE)
_PROMO = re.compile(r"\b(sale|% off|discount|offer|upgrade now|limited time|collab|partnership opportunity|"
                    r"feature your|sponsor)\b", re.IGNORECASE)
_NEWS = re.compile(r"\b(newsletter|this week in|weekly digest|unsubscribe|edition)\b", re.IGNORECASE)
_NO_REPLY = re.compile(r"^(no-?reply|do-?not-?reply|newsletter|news|deals|marketing)@", re.IGNORECASE)


def _text(email: dict) -> str:
    return f"{email.get('subject', '')}\n{email.get('body', '')}"


def rule_decision(email: dict) -> dict | None:
    sender, t = email.get("from", ""), _text(email)
    if _LOOKALIKE.search(sender) or (_PHISH.search(t) and "http" in t):
        return {"category": "Spam", "urgent": False, "needs_reply": False, "flag": "phishing",
                "summary": "Likely phishing: asks to verify an account through a link.", "confidence": 0.97}
    if _RECEIPT_SENDER.search(sender) and re.search(r"payment (received|captured|successful)", t, re.IGNORECASE):
        return {"category": "Invoice/Payment", "urgent": False, "needs_reply": False, "intent": "payment_receipt",
                "summary": "Payment gateway receipt.", "confidence": 0.95}
    return None


def is_vip(sender: str, vips: list[str]) -> bool:
    s = sender.lower()
    return any(s == v.lower() or s.endswith("@" + v.lower().lstrip("@")) for v in vips)


def heuristic_triage(email: dict, *, known_contact: bool = False) -> dict:
    """Keyword classifier for mock mode / outages. Deliberately simple and general."""
    if (d := rule_decision(email)) is not None:
        return d
    sender, t = email.get("from", ""), _text(email)
    urgent = bool(_URGENT.search(t))
    if _PRIZE.search(t):
        cat, reply = "Spam", False
    elif _NEWS.search(t) and not known_contact:
        cat, reply = "Newsletter", False
    elif _INVOICE.search(t):
        cat, reply = "Invoice/Payment", not _NO_REPLY.search(sender)
    elif known_contact:
        cat, reply = "Client", True
    elif _PROMO.search(t) or _NO_REPLY.search(sender):
        cat, reply = "Promotion", False
    elif _LEAD.search(t):
        cat, reply = "Lead", True
    elif urgent:
        cat, reply = "Urgent", True
    else:
        cat, reply = "Other", True
    if cat in ("Promotion", "Newsletter", "Spam"):
        urgent = False
    if re.search(r"\b(thanks|thank you)[!.]?\s*$", email.get("body", "").strip(), re.IGNORECASE) and len(t) < 160:
        reply = False
    return {"category": cat, "urgent": urgent, "needs_reply": reply,
            "summary": (email.get("subject") or "")[:120], "confidence": 0.5}


# ---------- fraud warnings (#20): deterministic signals, combined with the model's own "suspicious" judgement ----------

_BANK_CHANGE = re.compile(r"\b(new|changed?|updated?|different)\b.{0,40}\b(bank (account|details)|account (number|details)|ifsc|iban|"
                          r"beneficiary|upi id)\b|\bupdate your records\b.{0,60}\b(bank|account)\b|"
                          r"\b(pay|transfer|remit)\b.{0,40}\bto (this|our new|the following) account\b", re.IGNORECASE | re.DOTALL)
_GIFT_CARD = re.compile(r"\b(gift ?cards?|amazon (vouchers?|cards?)|google play cards?|itunes cards?)\b", re.IGNORECASE)
_SECRET = re.compile(r"\b(otp|one[- ]time password|verification code|pin)\b.{0,40}\b(share|send|tell|forward)\b|"
                     r"\b(share|send|tell|forward)\b.{0,40}\b(otp|one[- ]time password|verification code)\b", re.IGNORECASE | re.DOTALL)


def _domain(addr: str) -> str:
    return addr.rsplit("@", 1)[-1].lower().strip(">").strip() if "@" in addr else ""


def _close(a: str, b: str) -> bool:
    """Domains one or two edits apart (lookalikes such as acrne.com for acme.com), but not the same."""
    if a == b or abs(len(a) - len(b)) > 2:
        return False
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1] <= 2


def fraud_signals(email: dict, known_domains: list[str] | None = None) -> list[str]:
    """Reasons an email looks like fraud, for a warning on the card and the conversation (never blocks anything)."""
    sender, t = email.get("from", "").lower(), _text(email)
    dom, reasons = _domain(sender), []
    reply_to = (email.get("reply_to") or "").lower()
    if reply_to and _domain(reply_to) and _domain(reply_to) != dom:
        reasons.append(f"replies would go to a different domain ({_domain(reply_to)})")
    shown = (email.get("from_name") or "").lower()
    if "@" in shown and _domain(shown) and _domain(shown) != dom:
        reasons.append(f"the sender's name shows {_domain(shown)} but the email is from {dom}")
    if _BANK_CHANGE.search(t):
        reasons.append("asks to pay into new or changed bank details: confirm by phone before paying")
    if _GIFT_CARD.search(t):
        reasons.append("asks for gift cards")
    if _SECRET.search(t):
        reasons.append("asks for an OTP or verification code")
    free = {"gmail.com", "yahoo.com", "outlook.com", "hotmail.com", "icloud.com", "rediffmail.com"}
    lookalike = next((k for k in (known_domains or []) if k not in free and dom not in free and _close(dom, k)), None)
    if lookalike:
        reasons.append(f"the domain {dom} looks like {lookalike}, a contact you know")
    return reasons

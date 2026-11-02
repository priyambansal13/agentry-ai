"""Prompt-injection guard (ROADMAP-V3 A1): text from strangers that tries to steer the AI instead of talking to the business.

    scan     deterministic signals (no model, no cost, no network): instructions to ignore / replace the agent's rules,
             requests for its prompt or keys, fake role markers (system:, <|im_start|>, [INST]), "you are now / act as
             / developer mode" role-play, hidden characters, and long encoded blobs
    where    every chat turn (website, WhatsApp, Telegram, voice) before the agent runs: a flagged message gets a short
             holding reply, the conversation goes to a person, and no tool runs; emails: the reasons join inbox
             triage's fraud signals, so the card warns and nothing is sent automatically
Ordinary customers never trip it ("ignore my last message, I meant Tuesday" isn't an instruction to the AI).
"""
import re
import unicodedata

HOLDING_REPLY = "Thanks for your message. Someone from our team will reply to you here shortly."

_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("asks the AI to ignore its instructions", re.compile(
        r"\b(ignore|disregard|forget|override|bypass)\b[^.\n]{0,40}\b(all|any|the|your|previous|prior|above|earlier|system)\b[^.\n]{0,25}"
        r"\b(instructions?|rules?|prompts?|guidelines?|polic(y|ies)|directives?|constraints?)\b", re.IGNORECASE)),
    ("asks for the AI's prompt or settings", re.compile(
        r"\b(reveal|print|repeat|output|leak|dump|show me)\b[^.\n]{0,30}\b(your|the)\b[^.\n]{0,20}"
        r"\b(system prompt|initial prompt|hidden prompt|instructions|prompt|api key|secret key|password)s?\b"
        r"|\b(what is|what are|tell me|give me)\b[^.\n]{0,20}\b(your|the)\b[^.\n]{0,10}\b(system prompt|initial prompt|hidden prompt|api key|secret key)s?\b",
        re.IGNORECASE)),
    ("tries to give the AI a new role", re.compile(
        r"\b(you are now|from now on,? you (are|will)|pretend (to be|you are)|act as (an? )?(unrestricted|jailbroken|dan|developer|admin|system)|"
        r"developer mode|jailbreak|do anything now|DAN mode)\b", re.IGNORECASE)),
    ("contains fake system / role markers", re.compile(
        r"(<\|?(im_start|im_end|system|endoftext)\|?>|\[/?INST\]|^\s*#{2,}\s*(system|instruction)s?\b|^\s*(system|assistant)\s*:)",
        re.IGNORECASE | re.MULTILINE)),
    ("tells the AI to make an unauthorised offer", re.compile(
        r"\b(you must|you have to|you are required to|your new instruction is to)\b[^.\n]{0,40}\b(refund|discount|free|waive|approve|cancel|transfer)\b",
        re.IGNORECASE)),
]
_HIDDEN = re.compile("[\\u200b-\\u200f\\u202a-\\u202e\\u2060-\\u2064\\ufeff]")  # zero-width and direction marks
_BLOB = re.compile(r"[A-Za-z0-9+/=]{180,}")


def scan(text: str | None) -> dict:
    """{"suspicious": bool, "reasons": [...]}: reasons in plain words for the card a person sees."""
    t = text or ""
    reasons = [label for label, rx in _PATTERNS if rx.search(t)]
    hidden = len(_HIDDEN.findall(t))
    if hidden >= 3:
        reasons.append(f"contains {hidden} hidden characters")
    if _BLOB.search(t):
        reasons.append("contains a long encoded block")
    tags = sum(1 for ch in t if unicodedata.category(ch) == "Cf" and 0xE0000 <= ord(ch) <= 0xE007F)
    if tags:
        reasons.append("contains invisible tag characters")
    return {"suspicious": bool(reasons), "reasons": reasons}

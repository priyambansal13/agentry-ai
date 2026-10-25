"""Phone numbers (PHASE-4-VOICE.md 4.3): Agentry's numbers on LiveKit, each answered by one client's receptionist.

Each number gets its own LiveKit dispatch rule ("agentry <number>"): every call becomes a new room, and the
`agentry-voice` worker is dispatched with {"number": "+1..."} so it can find the client that owns the number
(app.connections, provider 'phone'). Numbers are rented in LiveKit Cloud (Telephony -> Phone Numbers); a SIP trunk
from another provider (Plivo, Exotel, Twilio) can feed the same rules later.
"""
import json

import httpx
from livekit import api
from sqlalchemy import text

from agentry.config import settings
from agentry.connectors.store import find_by_account, save_connection
from agentry.db import tenant_session
from agentry.leads import normalize_phone

AGENT_NAME = "agentry-voice"
RULE_PREFIX = "agentry "


class TelephonyError(Exception):
    pass


def _base() -> str:
    return settings.livekit_url.replace("wss://", "https://").replace("ws://", "http://")


def _token() -> str:
    return (api.AccessToken(settings.livekit_api_key, settings.livekit_api_secret)
            .with_sip_grants(api.SIPGrants(admin=True, call=True)).to_jwt())


async def _twirp(method: str, body: dict) -> dict:
    """LiveKit's PhoneNumberService has no Python SDK yet: call its Twirp API directly."""
    async with httpx.AsyncClient(timeout=20) as c:
        r = await c.post(f"{_base()}/twirp/livekit.PhoneNumberService/{method}", json=body,
                         headers={"Authorization": f"Bearer {_token()}"})
    if r.status_code != 200:
        raise TelephonyError(f"LiveKit {method}: {r.status_code} {r.text[:200]}")
    return r.json()


async def project_numbers() -> list[dict]:
    """The phone numbers rented in Agentry's LiveKit project."""
    items = (await _twirp("ListPhoneNumbers", {"limit": 100})).get("items", [])
    return [{"id": n["id"], "number": n["e164_format"], "country": n.get("country_code"), "locality": n.get("locality"),
             "status": n.get("status", "").removeprefix("PHONE_NUMBER_STATUS_").lower(),
             "dispatch_rule_id": n.get("sip_dispatch_rule_id") or None} for n in items]


async def _ensure_rule(lk: api.LiveKitAPI, number: str) -> str:
    """One dispatch rule per number: a new room per call, the voice agent dispatched with the dialled number."""
    name = RULE_PREFIX + number
    existing = [r for r in (await lk.sip.list_dispatch_rule(api.ListSIPDispatchRuleRequest())).items if r.name == name]
    if existing:
        return existing[0].sip_dispatch_rule_id
    rule = await lk.sip.create_dispatch_rule(api.CreateSIPDispatchRuleRequest(dispatch_rule=api.SIPDispatchRuleInfo(
        name=name,
        rule=api.SIPDispatchRule(dispatch_rule_individual=api.SIPDispatchRuleIndividual(room_prefix="call-")),
        room_config=api.RoomConfiguration(agents=[api.RoomAgentDispatch(agent_name=AGENT_NAME,
                                                                         metadata=json.dumps({"number": number}))]),
    )))
    return rule.sip_dispatch_rule_id


async def assign(org_id: str, number: str, staff_user_id: str | None = None) -> dict:
    """Give a client one of Agentry's numbers: route it to the voice agent and record it as the client's 'phone'
    connection (which also passes the receptionist's go-live check)."""
    e164 = normalize_phone(number, "US")
    if not e164:
        raise TelephonyError(f"{number} isn't a valid phone number")
    nums = {n["number"]: n for n in await project_numbers()}
    if e164 not in nums:
        raise TelephonyError(f"{number} isn't one of Agentry's LiveKit numbers")
    owner = await find_by_account("phone", e164)
    if owner and owner["org_id"] != org_id:
        raise TelephonyError(f"{e164} is already assigned to another client")
    lk = api.LiveKitAPI(_base(), settings.livekit_api_key, settings.livekit_api_secret)
    try:
        rule_id = await _ensure_rule(lk, e164)
    finally:
        await lk.aclose()
    # LiveKit rejects the singular sip_dispatch_rule_id here (400); the list form is accepted
    await _twirp("UpdatePhoneNumber", {"id": nums[e164]["id"], "sip_dispatch_rule_ids": [rule_id]})
    await save_connection(org_id, provider="phone", account_ref=e164, secret={}, display_name=e164,
                          state={"provider": "livekit", "number_id": nums[e164]["id"], "dispatch_rule_id": rule_id},
                          connected_by=staff_user_id)
    return {"number": e164, "dispatch_rule_id": rule_id}


async def unassign(org_id: str, number: str) -> None:
    """Take a number back from a client: calls to it are no longer answered for them (the rule stays, harmless)."""
    async with tenant_session(org_id) as conn:
        await conn.execute(text("update app.connections set status = 'revoked' where provider = 'phone' and account_ref = :n"),
                           {"n": number})

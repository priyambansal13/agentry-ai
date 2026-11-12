"""Missed-call recovery (automations/missed_call): the phone system's webhook and the portal page."""
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import text

from agentry.auth import OrgContext, require
from agentry.automations import missed_call as mc
from agentry.config import settings
from agentry.db import tenant_session
from agentry.features import require_page

hooks = APIRouter(tags=["hooks"])
router = APIRouter(prefix="/org/missed-calls", dependencies=[Depends(require_page("missed-calls"))])
Reader = Annotated[OrgContext, Depends(require("dashboard", "read"))]
Editor = Annotated[OrgContext, Depends(require("automation", "configure"))]


@hooks.post("/hooks/calls/{key}")
@hooks.get("/hooks/calls/{key}")  # some IVRs can only call a URL with query parameters
async def call_hook(key: str, request: Request) -> dict:
    ctype = request.headers.get("content-type", "")
    data: dict = dict(request.query_params)
    if request.method == "POST":
        try:
            data |= (await request.json()) if "json" in ctype else dict(await request.form())
        except ValueError:
            pass
    try:
        return await mc.receive(key, {k: v for k, v in data.items() if isinstance(v, (str, int, float, bool))})
    except LookupError as e:
        raise HTTPException(404, "unknown key") from e


@router.get("")
async def overview(ctx: Reader) -> dict:
    key = await mc.ensure_key(ctx.org_id)
    async with tenant_session(ctx.org_id) as conn:
        calls = (await conn.execute(text("""select m.id::text, m.caller, m.status, m.outcome, m.skip_reason, m.at, m.sent_at, m.replied_at, m.booked_at,
            m.conversation_id::text, c.name as contact from app.missed_calls m left join app.contacts c on c.id = m.contact_id
            order by m.at desc limit 100"""))).mappings().all()
        cfg = (await conn.execute(text("select config, status from app.automation_instances where template_key = 'missed_call_recovery'"))).mappings().one()
        stats = {"30": await mc.summary(conn, 30), "1": await mc.summary(conn, 1)}
    return {"hook_url": f"{settings.api_public_url.rstrip('/')}/hooks/calls/{key}", "status": cfg["status"],
            "callers_informed": bool((cfg["config"] or {}).get("callers_informed")), "template": (cfg["config"] or {}).get("whatsapp_template"),
            "stats": stats, "calls": [dict(c) for c in calls]}


@router.post("/test")
async def test_call(ctx: Editor, request: Request) -> dict:
    """A pretend missed call from a number the business gives (their own phone), to see the whole flow."""
    body = await request.json()
    key = await mc.ensure_key(ctx.org_id)
    return await mc.receive(key, {"From": str(body.get("phone") or "")[:20], "Status": "no-answer", "provider": "test"})

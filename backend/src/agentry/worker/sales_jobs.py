"""Agentry's own sales pipeline in the worker: a new demo request (team alert, confirmation, lead in Agentry's own
organisation) and the follow-ups after a demo is sent (agentry/sales.py)."""
import asyncio
import json
from datetime import datetime
from typing import Any

from dbos import DBOS, SetWorkflowID
from sqlalchemy import text

from agentry import sales
from agentry.config import settings
from agentry.db import system_session
from agentry.notify.email import send_email
from agentry.worker.handlers import on


@DBOS.step()
async def load_demo_request(demo_id: str) -> dict:
    return json.loads(json.dumps(await sales.get(demo_id), default=str))  # step results must serialise


@DBOS.step(retries_allowed=True, max_attempts=5)
async def email_step(to: str, subject: str, body: str) -> None:
    await asyncio.to_thread(send_email, to, subject, body)


@DBOS.step()
async def mirror_lead_step(demo_id: str) -> str | None:
    return await sales.mirror_lead(demo_id)


@on("demo_request.created")
@DBOS.workflow()
async def on_demo_request(event: dict) -> None:
    """Tell the Agentry team, confirm to the prospect, and add them to Agentry's own leads."""
    d = await load_demo_request(event["payload"]["demo_request_id"])
    await email_step(
        settings.ops_email,
        f"New demo request: {d['company'] or d['name']}",
        "\n".join(f"{k}: {d[k]}" for k in ("name", "email", "phone", "company", "website", "niche", "message"))
        + f"\n\nOpen it in Agentry HQ: {settings.dashboard_url}/hq/demo-requests/{d['id']}",
    )
    await email_step(d["email"], *sales.confirmation_email(d))
    await mirror_lead_step(d["id"])


# ---------- follow-ups after the demo email ----------

@DBOS.step()
async def follow_up_plan(demo_id: str) -> dict:
    d = await sales.get(demo_id)
    action, seconds = sales.next_follow_up(d)
    return {"action": action, "seconds": seconds}


@DBOS.step()
async def send_follow_up(demo_id: str) -> bool:
    """Send the next follow-up if it is still due (status unchanged), and count it."""
    d = await sales.get(demo_id)
    if sales.next_follow_up(d)[0] != "send":
        return False
    # Claim this follow-up first: after "Send again" an older schedule may wake at the same moment, and only one of
    # them may send it.
    async with system_session() as conn:
        claimed = (await conn.execute(text("""update app.demo_requests set followups_sent = followups_sent + 1, updated_at = now()
            where id = cast(:i as uuid) and followups_sent = :n and status = 'demo_sent' returning id"""),
            {"i": demo_id, "n": d["followups_sent"]})).first()
    if not claimed:
        return False
    await asyncio.to_thread(send_email, d["email"], *sales.follow_up_email(d, d["followups_sent"]))
    return True


@DBOS.workflow()
async def run_follow_ups(demo_id: str) -> str:
    for _ in range(60):  # each wait is at most a day; the last follow-up is on day 10
        plan = await follow_up_plan(demo_id)
        if plan["action"] == "done":
            return "done"
        if plan["action"] == "send":
            await send_follow_up(demo_id)
            continue
        await DBOS.sleep_async(min(plan["seconds"], 86400))  # durable; re-checks the status at least daily
    return "iteration cap"


@on("demo.sent")
@DBOS.workflow()
async def on_demo_sent(event: dict) -> None:
    demo_id = event["payload"]["demo_request_id"]
    # its own workflow (not the events queue): it sleeps for days; one per sending of the demo
    with SetWorkflowID(f"demo-follow-ups-{demo_id}-{event['payload'].get('sent_at', '')}"):
        await DBOS.start_workflow_async(run_follow_ups, demo_id)


# ---------- replies in the sales inbox, proposal views ----------

@DBOS.step()
async def read_sales_inbox() -> list[dict]:
    from agentry import sales_inbox
    messages = await asyncio.to_thread(sales_inbox.fetch_recent)
    return await sales_inbox.process(messages)


@DBOS.step()
async def act_on_message(m: dict) -> None:
    """A real reply moves the request to "in talks" (follow-ups stop); replies and bounces alert the team."""
    d = await sales.get(m["demo_request_id"])
    who = d["company"] or d["name"]
    link = f"{settings.dashboard_url}/hq/demo-requests/{d['id']}"
    if m["kind"] == "reply":
        if m["status_before"] in ("new", "demo_built", "demo_sent"):
            await sales.update(d["id"], status="in_talks")
        await asyncio.to_thread(send_email, settings.ops_email, f"{who} replied: {m['subject']}",
                                f"{m['snippet'] or '(no text)'}\n\nThe request is now \"in talks\" and follow-ups have stopped.\nOpen: {link}")
    elif m["kind"] == "bounce":
        await asyncio.to_thread(send_email, settings.ops_email, f"Email to {who} bounced",
                                f"An email to {d['email']} couldn't be delivered. Check the address with them.\nOpen: {link}")


@DBOS.workflow()
async def check_sales_inbox(scheduled_time: datetime, context: Any) -> None:
    for m in await read_sales_inbox():
        await act_on_message(m)


@DBOS.step()
async def proposal_viewed_alert(proposal_id: str) -> None:
    async with system_session() as conn:
        p = (await conn.execute(text("select business, email, sent_at from app.proposals where id = cast(:i as uuid)"),
                                {"i": proposal_id})).mappings().one()
    await asyncio.to_thread(send_email, settings.ops_email, f"{p['business']} opened your proposal",
                            f"{p['email']} just opened the proposal you sent on {p['sent_at']:%d %b, %H:%M}. A good moment to follow up.")


@on("proposal.viewed")
@DBOS.workflow()
async def on_proposal_viewed(event: dict) -> None:
    await proposal_viewed_alert(event["payload"]["proposal_id"])

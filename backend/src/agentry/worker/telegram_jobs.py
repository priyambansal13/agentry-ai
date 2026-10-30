"""Telegram in the worker: push new Needs-you cards to the team bot, tell people when their content is ready, and (local
development, "polling" mode) fetch new messages for the team bot and every business bot every few seconds."""
from dbos import DBOS
from sqlalchemy import text

from agentry import telegram_team
from agentry.config import settings
from agentry.connectors import telegram
from agentry.connectors.store import _with_secret
from agentry.db import system_session, tenant_session
from agentry.worker.handlers import on


@DBOS.step()
async def push_card_step(org_id: str, approval_id: str) -> int:
    return await telegram_team.push_card(org_id, approval_id)


@on("approval.created")
@DBOS.workflow()
async def card_to_telegram(event: dict) -> None:
    if telegram_team.enabled():
        await push_card_step(event["org_id"], event["payload"]["approval_id"])


@DBOS.step()
async def content_ready_step(org_id: str, source_id: str) -> bool:
    async with tenant_session(org_id) as conn:
        row = (await conn.execute(text("""select s.title, l.chat_id, (select count(*) from app.content_posts p where p.source_id = s.id) as posts
            from app.content_sources s join app.telegram_links l on l.user_id = s.created_by where s.id = cast(:i as uuid)"""),
            {"i": source_id})).mappings().first()
    if not row:
        return False
    return await telegram_team.send_alert(row["chat_id"], f"{row['posts']} posts ready to review",
                                          f"From “{row['title']}”.\n{telegram_team.link_to(f'/content/{source_id}')}")


@on("content.ready")
@DBOS.workflow()
async def content_ready_to_telegram(event: dict) -> None:
    if telegram_team.enabled():
        await content_ready_step(event["org_id"], event["payload"]["source_id"])


async def poll_once() -> int:
    """Polling mode only: one round of getUpdates for every bot. Returns how many updates were handled."""
    if telegram.mode() != "polling":
        return 0
    handled = 0
    if telegram_team.enabled():
        try:
            for u in await telegram.updates("agentry", settings.telegram_bot_token):
                await telegram_team.handle_update(u)
                handled += 1
        except telegram.TelegramError:
            pass  # a bad token or Telegram being down: try again next round
    async with system_session() as conn:
        rows = (await conn.execute(text("select * from app.connections where provider = 'telegram' and status = 'connected'"))).mappings().all()
    for row in rows:
        c = _with_secret(row)
        try:
            for u in await telegram.updates(c["id"], c["secret"]["bot_token"]):
                handled += await telegram.ingest_customer(c, u)
        except telegram.TelegramError:
            continue
    return handled


async def poll_forever(every_seconds: float = 3) -> None:
    """Local development: a plain loop in the worker (not a durable workflow: a missed round is harmless, the stored
    offsets make the next round pick up where this one stopped, and it would otherwise write ~30k workflow rows a day)."""
    import asyncio
    while True:
        try:
            await poll_once()
        except Exception as e:  # noqa: BLE001 - keep polling; one bad update mustn't stop the bot
            print(f"telegram polling: {e}")
        await asyncio.sleep(every_seconds)

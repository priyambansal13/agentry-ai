"""Inbox triage jobs that need the Gmail connector: learning the writing style (#1)."""
from dbos import DBOS

from agentry.worker.handlers import on


@DBOS.step()
async def learn_style_step(org_id: str) -> dict:
    from agentry.automations.inbox_triage.style import learn_style
    return await learn_style(org_id)


@on("inbox.learn_style")
@DBOS.workflow()
async def on_learn_style(event: dict) -> None:
    await learn_style_step(event["org_id"])

"""Content repurposing (docs/automations/content-repurposing.md, docs/PHASE-6-CONTENT.md).

One long video or podcast -> the best moments -> a post per platform with a quote card -> human review -> calendar ->
published at the slot time. sources.py (upload, transcription), moments.py, drafts.py (LangGraph draft/critic loop),
images.py + brand.py (quote cards, brand voice), pipeline.py (the workflow), calendar.py (slots, publishing).
Publishing is "test mode" (recorded, not posted) until social accounts are connected (6.5).
"""
from dbos import DBOS
from pydantic import BaseModel, Field

from agentry.automations import AutomationTemplate, register
from agentry.worker.handlers import on


class ContentConfig(BaseModel):
    call_to_action: str | None = Field(None, title="Call to action to use when it fits",
                                       description="e.g. 'Book a check-up at smilecraft.example'. Used sparingly, never invented.",
                                       json_schema_extra={"editable_by": "client"})


register(AutomationTemplate(
    key="content_repurposing",
    name="Content repurposing",
    description="Turns one long video or podcast into ~30 posts for LinkedIn, Instagram and X, with branded images, for you to approve.",
    config_model=ContentConfig,
    metrics=("posts_published",),
))


@on("content.source_added")
@DBOS.workflow()
async def on_source_added(event: dict) -> None:
    from agentry.automations.content.pipeline import start
    await start(event["org_id"], event["payload"]["source_id"], event["payload"].get("attempt", 0))

"""Personal cold email (docs/automations/cold-email.md, docs/PHASE-5-COLD-EMAIL.md).

Built so far: 5.1 prospect pipeline (pipeline.py, providers.py with mocks), 5.2 research + fact-checked first lines
(research.py), 5.3 review in the portal (api/routes/cold_email.py). Sending (5.4) and replies (5.5) come next, so
this automation never sends anything yet.
"""
from dbos import DBOS
from pydantic import BaseModel, Field

from agentry.automations import AutomationTemplate, register
from agentry.worker.handlers import on


class ColdEmailConfig(BaseModel):
    pitch: str | None = Field(None, title="What you offer, in one sentence",
                              description="Used to write the rest of the email once sending is switched on.",
                              json_schema_extra={"editable_by": "client"})
    postal_address: str | None = Field(None, title="Business postal address (shown in every email)",
                                       description="Required by anti-spam laws (CAN-SPAM).", json_schema_extra={"editable_by": "client"})
    allow_catch_all: bool = Field(False, title="Also email addresses that can't be fully verified (catch-all)",
                                  json_schema_extra={"editable_by": "agentry"})
    allow_eu_uk: bool = Field(False, title="Include EU/UK businesses (needs a legitimate-interest note)",
                              json_schema_extra={"editable_by": "agentry"})


register(AutomationTemplate(
    key="cold_email",
    name="Personal cold email",
    description="Finds businesses that fit, finds the person who decides, and writes one honest first line from their own website.",
    config_model=ColdEmailConfig,
    metrics=("prospects_found", "meetings_booked"),
))


@on("cold_email.build_requested")
@DBOS.workflow()
async def on_build_requested(event: dict) -> None:
    from agentry.automations.cold_email.pipeline import start_build
    await start_build(event["org_id"], event["payload"]["campaign_id"])

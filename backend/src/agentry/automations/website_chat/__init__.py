from typing import Literal

from pydantic import BaseModel, Field

from agentry.automations import AutomationTemplate, register


class WebsiteChatConfig(BaseModel):
    """Website chat agent settings (docs/automations/boring-machine.md §2.1)."""

    position: Literal["bottom-right", "bottom-left"] = Field("bottom-right", title="Bubble position",
                                                               json_schema_extra={"editable_by": "client"})
    open_after_seconds: int | None = Field(None, ge=3, le=120, title="Open automatically after (seconds)",
                                           json_schema_extra={"editable_by": "client"})
    allowed_domains: list[str] = Field(default_factory=list, title="Websites allowed to embed the chat",
                                       json_schema_extra={"editable_by": "client"})
    handoff_alerts: bool = Field(True, title="Alert me when a visitor asks for a person",
                                 json_schema_extra={"editable_by": "client"})


TEMPLATE = register(AutomationTemplate(
    key="website_chat",
    name="Website chat agent",
    description="Greets visitors, answers from your knowledge, asks need/budget/timeline, books calls, hands off to you.",
    config_model=WebsiteChatConfig,
    metrics=("leads_captured", "appointments_booked"),
))

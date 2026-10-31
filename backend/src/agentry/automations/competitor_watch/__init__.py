"""Competitor & price watch (ROADMAP-V2 10.1): the business lists pages to watch (a competitor's offers, a supplier's
or rival's product price); Watchers (agentry.watchers) checks them and reports meaningful changes."""
from pydantic import BaseModel, Field

from agentry.automations import AutomationTemplate, register


class CompetitorWatchConfig(BaseModel):
    check_every_hours: int = Field(6, ge=1, le=72, title="Check each page every (hours)", json_schema_extra={"editable_by": "client"})
    min_change_pct: float = Field(5, ge=0.5, le=50, title="Tell me about price changes of at least (%)", json_schema_extra={"editable_by": "client"})
    max_pages: int = Field(20, ge=1, le=100, title="Pages included in your plan", json_schema_extra={"editable_by": "agentry"})


register(AutomationTemplate(
    key="competitor_watch",
    name="Competitor & price watch",
    description="Watches competitors' pages and product prices and tells you, in plain words, when something changes.",
    config_model=CompetitorWatchConfig,
    metrics=("changes_spotted",),
))

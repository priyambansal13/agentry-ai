"""Automation templates: each automation's key, name, client-editable config schema and metrics.

The portal renders settings forms from `config_model.model_json_schema()`; fields marked
json_schema_extra={"editable_by": "agentry"} are shown read-only to clients (docs/CLIENT-PORTAL.md §1.3).
"""
from dataclasses import dataclass, field

from pydantic import BaseModel


@dataclass(frozen=True)
class AutomationTemplate:
    key: str
    name: str
    description: str
    config_model: type[BaseModel]
    metrics: tuple[str, ...] = field(default_factory=tuple)


REGISTRY: dict[str, AutomationTemplate] = {}


def register(t: AutomationTemplate) -> AutomationTemplate:
    REGISTRY[t.key] = t
    return t


def default_config(key: str) -> dict:
    t = REGISTRY.get(key)
    return t.config_model().model_dump() if t else {}


def load_all() -> None:
    """Import every automation package so its template and event handlers register."""
    from agentry.automations import (  # noqa: F401
        ai_receptionist,
        appointment_concierge,
        bookkeeping,
        ca,
        cold_email,
        competitor_watch,
        content,
        inbox_triage,
        invoice_follow_up,
        lead_reactivation,
        lead_research,
        reviews,
        speed_to_lead,
        telegram_assistant,
        video_studio,
        website_chat,
        whatsapp_assistant,
    )

    # workflows that are only imported lazily must still be registered at start, or DBOS can't resume them after a restart
    from agentry.automations.cold_email import pipeline as _cold_pipeline  # noqa: F401
    from agentry.automations.content import longform, pipeline  # noqa: F401
    from agentry.voice import summary  # noqa: F401 - call summaries after voice calls
    from agentry.worker import (
        delivery,  # noqa: F401 - outbound delivery + Gmail sync workflows
        inbox_jobs,  # noqa: F401 - writing style from sent mail
        notify_jobs,  # noqa: F401 - Notification Center: any event -> rules -> channels
        sales_jobs,  # noqa: F401 - Agentry's own demo requests and follow-ups
        sequence_handlers,  # noqa: F401
        telegram_jobs,  # noqa: F401 - Telegram cards, content-ready messages, polling
    )

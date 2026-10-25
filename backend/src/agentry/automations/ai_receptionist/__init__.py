"""AI receptionist: the client's agent (same AgentSpec as website chat and WhatsApp) answering phone calls.

The call itself runs in the voice worker (agentry/voice/worker.py); after it, voice/summary.py writes the summary and,
when a person should follow up, a "Call back" card. Phone numbers, call forwarding and live transfer arrive with
PHASE-4-VOICE.md milestones 4.3-4.4: until then calls are browser test calls and go-live waits for a phone number.
"""
from typing import Literal

from pydantic import BaseModel, Field

from agentry.automations import AutomationTemplate, register


class ReceptionistConfig(BaseModel):
    answer_when: Literal["after_hours", "busy_or_no_answer", "always"] = Field(
        "after_hours", title="When the AI answers",
        description="Start with after-hours calls, review the first calls together, then widen. Takes effect once your phone number is connected.",
        json_schema_extra={"editable_by": "client", "enum_labels": {
            "after_hours": "After hours only", "busy_or_no_answer": "When we're busy or don't answer", "always": "Always"}})
    transfer_number: str | None = Field(None, title="Number to transfer callers who want a person",
                                        description="A staff phone in international format, e.g. +919876543210. Until live transfer arrives, callers get a call-back card instead.",
                                        pattern=r"^\+[1-9]\d{7,14}$", json_schema_extra={"editable_by": "client"})


register(AutomationTemplate(
    key="ai_receptionist",
    name="AI receptionist",
    description="Answers your calls 24/7: questions from your knowledge, books appointments, takes messages for a call back.",
    config_model=ReceptionistConfig,
    metrics=("leads_captured", "appointments_booked"),
))

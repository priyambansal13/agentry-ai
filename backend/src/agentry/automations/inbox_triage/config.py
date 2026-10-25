from typing import Annotated, Literal

from pydantic import BaseModel, Field

CATEGORIES = ["Client", "Lead", "Invoice/Payment", "Urgent", "Promotion", "Newsletter", "Spam", "Other"]


class TriageConfig(BaseModel):
    """Inbox triage settings (docs/automations/inbox-triage.md §2.1)."""

    vip_senders: list[str] = Field(default_factory=list, title="VIP senders",
                                   description="Emails or domains whose messages are always treated as urgent.",
                                   json_schema_extra={"editable_by": "client"})
    alert_channel: Literal["telegram", "whatsapp", "email"] = Field(
        "email", title="Urgent alerts via", json_schema_extra={"editable_by": "client", "enum_labels": {
            "email": "Each person's choice: email or WhatsApp (Account & notifications)",
            "whatsapp": "Each person's choice: email or WhatsApp (same as above)", "telegram": "Telegram group chat"}})
    telegram_chat_id: str | None = Field(None, title="Telegram chat ID", json_schema_extra={"editable_by": "client"})
    quiet_hours: tuple[str, str] = Field(("21:00", "08:00"), title="Quiet hours (no alerts)",
                                         json_schema_extra={"editable_by": "client"})
    max_alerts_per_hour: int = Field(5, ge=1, le=60, title="Max urgent alerts per hour",
                                     json_schema_extra={"editable_by": "client"})
    owner_alert: Literal["immediately", "if_unanswered"] = Field(
        "immediately", title="Alert the owner",
        description="Immediately, or only if an urgent email is still unanswered (the team is alerted first).",
        json_schema_extra={"editable_by": "client", "enum_labels": {
            "immediately": "Immediately, with the team", "if_unanswered": "Only if still unanswered (team first)"}})
    escalate_after_minutes: int = Field(30, ge=0, le=240, title="Alert again if still unanswered after (minutes)",
                                        description="A second alert, to the owner, when nobody has replied. 0 = never.",
                                        json_schema_extra={"editable_by": "client"})
    draft_replies: bool = Field(True, title="Draft replies for emails that need one",
                                json_schema_extra={"editable_by": "client"})
    archive_promotions: bool = Field(False, title="Archive promotions and spam automatically",
                                     json_schema_extra={"editable_by": "client"})
    digest_hour: int = Field(8, ge=0, le=23, title="Daily digest hour (local time)",
                             json_schema_extra={"editable_by": "client"})
    categories: list[str] = Field(default_factory=lambda: list(CATEGORIES), title="Built-in categories",
                                  json_schema_extra={"editable_by": "agentry"})
    custom_categories: list[Annotated[str, Field(min_length=2, max_length=30, pattern=r"^[^/,]+$")]] = Field(
        default_factory=list, max_length=10, title="Your own categories",
        description="Extra labels for your business, e.g. Supplier, Job applicant, Government. Agentry learns what fits each.",
        json_schema_extra={"editable_by": "client"})
    auto_send_categories: list[str] = Field(
        default_factory=list, title="Send drafts automatically for (categories)",
        description="Only once the agent is switched to automatic, and only for categories where your team sent at least "
                    "10 recent drafts unchanged. Never for urgent, suspicious or drafts with [gaps].",
        json_schema_extra={"editable_by": "client"})
    auto_send_min_approved: int = Field(10, ge=3, le=100, title="Drafts sent unchanged before a category may auto-send",
                                        json_schema_extra={"editable_by": "agentry"})
    nudge_after_days: int = Field(3, ge=0, le=30, title="Suggest a follow-up when a client or lead hasn't replied for (days)",
                                  description="A follow-up draft appears in Needs you. 0 = never.",
                                  json_schema_extra={"editable_by": "client"})
    keep_email_text_days: int = Field(30, ge=7, le=365, title="Keep the full text of emails for (days)",
                                      description="After this, only the summary, labels and replies are kept.",
                                      json_schema_extra={"editable_by": "client"})

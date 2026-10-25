from agentry.automations import AutomationTemplate, register
from agentry.automations.inbox_triage.config import TriageConfig

TEMPLATE = register(AutomationTemplate(
    key="inbox_triage",
    name="Inbox triage",
    description="Sorts every new email, labels it, alerts you about urgent ones and drafts replies for you to send.",
    config_model=TriageConfig,
    metrics=("emails_triaged",),
))

from agentry.automations.inbox_triage import digest, workflow  # noqa: F401 - registers workflows and handlers

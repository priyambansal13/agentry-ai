"""CA Firm pack agents (docs/PACKS.md). Shared clients, filings and files live in core.py; each agent is its own module."""
from agentry.automations.ca import (  # noqa: F401
    audit3cd,
    bank,
    calendar,
    capgains,
    chaser,
    core,
    excel,
    gst,
    itr,
    notices,
    recurring,
    taxdocs,
    tds,
    tracker,
)

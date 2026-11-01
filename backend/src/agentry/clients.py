"""Onboarding a client from Agentry HQ: their settings, the automations they bought, onboarding steps and pricing plan.

The organisation itself (and the owner's invitation) is created by the dashboard, which owns the auth schema; this
module provisions everything else in one transaction. Automations start in "setup" and switch to approval mode at go-live.
"""
import json
import secrets

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from agentry import agent_packs, audit, billing
from agentry.automations import REGISTRY, default_config
from agentry.features import FEATURES, for_automations


class ProvisionError(ValueError):
    pass


# shown next to an automation in HQ while part of it is still being built
NOTES = {"ai_receptionist": "Assign it a phone number on the client page (US numbers on LiveKit for now)",
         "cold_email": "Test mode: sample prospect lists and a test sender until Instantly and data providers are connected",
         "content_repurposing": "Test mode: posts are scheduled and recorded, not posted, until social accounts are connected"}

# automations without a registered template (yet): their catalog name and one-line description
NAMES = {
    "ai_receptionist": ("AI receptionist", "Answers calls 24/7, books appointments, transfers when needed."),
    "cold_email": ("Personal cold email", "Researches prospects and sends personal first emails from your domains."),
    "content_repurposing": ("Content repurposing", "Turns one long video into 30 posts with images."),
    "ca_document_chaser": ("Document chaser", "A checklist per client per filing; WhatsApp and email reminders until every document is in."),
    "ca_tax_docs_reader": ("Tax documents reader", "Form 16, AIS, TIS and 26AS into one sheet per client, with mismatches flagged."),
    "ca_filing_tracker": ("Filing tracker", "Every filing on one board (docs pending to verified); clients ask its status on WhatsApp."),
    "ca_compliance_calendar": ("Compliance calendar", "GST, TDS, advance tax, ROC and PF/ESI dates per client, with reminders."),
    "ca_itr_prep": ("ITR preparation", "Tax computation, old vs new regime, and the ITR JSON for the CA to review and upload."),
    "ca_capital_gains": ("Capital gains", "Broker P&L and mutual fund statements to STCG/LTCG and Schedule CG."),
    "ca_bank_classifier": ("Bank statement classifier", "Statement lines tagged and summed into a trial balance or 44AD/44ADA working."),
    "ca_notice_handler": ("Notice handler", "Income-tax notices explained, the difference computed and a reply drafted."),
    "ca_gst_reconciliation": ("GST reconciliation", "GSTR-2B vs the purchase register, with messages to suppliers who haven't filed."),
    "ca_tds_returns": ("TDS returns", "24Q/26Q data, PAN checks, late-deduction interest, Form 16/16A sent out."),
    "ca_tax_audit": ("Tax audit (3CD)", "3CD clauses filled from the books, exceptions flagged for the auditor."),
    "recurring_books": ("Recurring entries & budgets", "Rent, retainers and EMIs booked on their dates; alerts at 80% of a budget."),
    "excel_desk": ("Excel desk", "Any PDF to Excel in your layout, reconciliations, and questions answered from your sheets."),
}


def catalog() -> list[dict]:
    """Every automation Agentry sells, and whether it can be switched on today."""
    out = []
    for key, f in FEATURES.items():
        t = REGISTRY.get(key)
        name, desc = (t.name, t.description) if t else NAMES.get(key, (key, ""))
        out.append({"key": key, "name": name, "description": desc, "available": f.available and t is not None,
                    "pages": list(f.pages), "connections": list(f.connections), "note": NOTES.get(key)})
    return out


def _check_keys(keys: list[str]) -> list[str]:
    keys = list(dict.fromkeys(keys))
    unknown = [k for k in keys if k not in FEATURES]
    unavailable = [k for k in keys if k in FEATURES and (not FEATURES[k].available or k not in REGISTRY)]
    if unknown or unavailable:
        raise ProvisionError(f"can't switch on: {', '.join(unknown + unavailable)}")
    return keys


async def provision(conn: AsyncConnection, org_id: str, *, name: str, country: str, timezone: str, currency: str,
                    website: str | None, automations: list[str], plan: billing.PricingPlan | None, staff_user_id: str,
                    pack: str | None = None, pack_agents: list[str] | None = None) -> dict:
    """`conn` is a tenant session for org_id. Fails if the client was already provisioned. `automations` are standalone
    add-ons; `pack` (with `pack_agents`, or the pack's defaults) adds a pack, whose price is used when no plan is given."""
    keys = _check_keys(automations)
    if not keys and not pack:
        raise ProvisionError("choose at least one automation or a pack")
    if (await conn.execute(text("select 1 from app.org_settings"))).first():
        raise ProvisionError("this client is already set up")
    persona = {"name": "Ava", "tone": "warm, professional and concise",
               "greeting": f"Hi! I'm Ava, {name}'s AI assistant. How can I help?", "signoff": f"Team {name}"}
    await conn.execute(text("""insert into app.org_settings (org_id, status, country, timezone, currency, website, persona, widget_key)
        values (:o, 'onboarding', :c, :tz, :cur, :w, cast(:p as jsonb), :wk)"""),
        {"o": org_id, "c": country, "tz": timezone, "cur": currency, "w": website, "p": json.dumps(persona),
         "wk": "wk_" + secrets.token_urlsafe(18)})
    for k in keys:
        await conn.execute(text("""insert into app.automation_instances (org_id, template_key, status, config)
            values (:o, :k, 'setup', cast(:c as jsonb))"""), {"o": org_id, "k": k, "c": json.dumps(default_config(k))})
    if pack:
        try:
            await agent_packs.assign(conn, org_id, pack, pack_agents, apply_pricing=plan is None, staff_user_id=staff_user_id)
        except agent_packs.PackError as e:
            raise ProvisionError(str(e)) from e
        keys = list((await conn.execute(text("select template_key from app.automation_instances order by 1"))).scalars())
    features = for_automations(keys)
    await _add_steps(conn, org_id, features["steps"])
    if plan:
        await billing.save_plan(conn, org_id, plan)
    await audit.record(conn, org_id=org_id, actor_type="agentry_staff", actor_user_id=staff_user_id, action="client.created",
                       metadata={"automations": keys, "plan": bool(plan), "pack": pack})
    return features


async def _add_steps(conn: AsyncConnection, org_id: str, steps: list[str]) -> None:
    for s in steps:
        await conn.execute(text("""insert into app.onboarding_progress (org_id, step_key, status) values (:o, :s, 'todo')
            on conflict (org_id, step_key) do nothing"""), {"o": org_id, "s": s})


async def set_automation(conn: AsyncConnection, org_id: str, key: str, enabled: bool, staff_user_id: str) -> dict:
    """Switch an automation on (an upsell) or off for a client. Switching off keeps its history (conversations,
    invoices, leads) but hides its sections and stops it. A client that is already live gets the new one in approval
    mode, so nothing is sent without a person approving it."""
    if enabled:
        _check_keys([key])
        live = (await conn.execute(text("select status = 'live' from app.org_settings"))).scalar_one_or_none()
        if live is None:
            raise ProvisionError("this client isn't set up yet")
        await conn.execute(text("""insert into app.automation_instances (org_id, template_key, status, config)
            values (:o, :k, :s, cast(:c as jsonb)) on conflict (org_id, template_key) do nothing"""),
            {"o": org_id, "k": key, "s": "approval_mode" if live else "setup", "c": json.dumps(default_config(key))})
    else:
        remaining = (await conn.execute(text("select count(*) from app.automation_instances where template_key <> :k"),
                                        {"k": key})).scalar_one()
        if remaining == 0:
            raise ProvisionError("a client needs at least one automation: pause the client instead")
        await conn.execute(text("delete from app.automation_instances where template_key = :k"), {"k": key})
    keys = list((await conn.execute(text("select template_key from app.automation_instances order by 1"))).scalars())
    features = for_automations(keys)
    await _add_steps(conn, org_id, features["steps"])
    await audit.record(conn, org_id=org_id, actor_type="agentry_staff", actor_user_id=staff_user_id,
                       action=f"automation.{'enabled' if enabled else 'disabled'}", target_type="automation", target_id=key)
    return features

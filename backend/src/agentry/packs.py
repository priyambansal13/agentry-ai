"""Industry packs (backend/packs/*.yaml): everything a niche needs preconfigured (docs/GO-TO-MARKET.md §1).

apply_pack() fills an organisation's persona, qualification questions, services and staff, starter FAQs and
automation instances. Client-specific values (their real services, hours, FAQs) override the pack's.
"""
import json
import secrets
from functools import lru_cache

import yaml
from sqlalchemy import text

from agentry.automations import default_config
from agentry.booking import set_catalog
from agentry.config import BACKEND
from agentry.db import tenant_session
from agentry.knowledge import add_faqs

PACKS = BACKEND / "packs"


@lru_cache
def load_pack(key: str) -> dict:
    path = PACKS / f"{key}.yaml"
    if not path.exists():
        raise KeyError(f"unknown pack {key}")
    return yaml.safe_load(path.read_text())


def list_packs() -> list[dict]:
    return [{k: p[k] for k in ("key", "name", "for", "featured")} for p in map(load_pack, sorted(x.stem for x in PACKS.glob("*.yaml")))]


async def apply_pack(org_id: str, pack_key: str, *, business: str, currency: str = "INR",
                     persona: dict | None = None, services: list[dict] | None = None, staff: list[dict] | None = None,
                     faqs: list[dict] | None = None, automations: dict[str, str] | None = None,
                     extra_profile: dict | None = None) -> None:
    pack = load_pack(pack_key)
    p = {**pack["persona"], **(persona or {})}
    p["greeting"] = p["greeting"].replace("{business}", business)
    profile = {"customer_value": pack["customer_value"].get(currency), "qualified_when": pack.get("qualified_when"),
               "safety": pack.get("safety"), **(extra_profile or {})}
    async with tenant_session(org_id) as conn:
        await conn.execute(text("""update app.org_settings set industry_pack = :k, persona = cast(:p as jsonb),
            qualification = cast(:q as jsonb), profile = profile || cast(:pr as jsonb),
            widget_key = coalesce(widget_key, :w)"""),
            {"k": pack_key, "p": json.dumps(p), "q": json.dumps(pack["qualification"]),
             "pr": json.dumps({k: v for k, v in profile.items() if v is not None}), "w": "wk_" + secrets.token_urlsafe(18)})
        for key, status in (automations or {}).items():
            await conn.execute(text("""insert into app.automation_instances (org_id, template_key, status, config)
                values (:o, :k, :s, cast(:c as jsonb)) on conflict (org_id, template_key) do update set status = excluded.status"""),
                {"o": org_id, "k": key, "s": status, "c": json.dumps(default_config(key))})
    await set_catalog(org_id, services or pack["services"], staff or pack["staff"])
    await add_faqs(org_id, faqs if faqs is not None else pack["faqs"])

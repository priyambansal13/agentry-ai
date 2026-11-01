"""Packs (docs/PACKS.md): sellable bundles of agents, e.g. the CA Firm pack.

A pack lists agents (each on or off by default) and a suggested price per currency; Agentry staff edit packs in HQ.
A client has at most one pack, tailored to them (which of its agents are on), plus any number of standalone add-ons.
Agents that are still being built can be in a pack: the client's pack keeps them, and they're switched on once built.
Industry packs (packs.py: persona, FAQs, services) are a different thing.
"""
import json
from typing import Annotated

from pydantic import BaseModel, Field, model_validator
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from agentry import audit, billing
from agentry.automations import REGISTRY, default_config
from agentry.features import FEATURES, for_automations


class PackError(ValueError):
    pass


class PackAgent(BaseModel):
    key: str
    default_on: bool = True


class PackIn(BaseModel):
    name: Annotated[str, Field(min_length=2, max_length=60)]
    tagline: Annotated[str, Field(max_length=160)] = ""
    audience: Annotated[str, Field(max_length=200)] = ""
    agents: Annotated[list[PackAgent], Field(min_length=1, max_length=40)]
    pricing: dict[str, billing.PricingPlan] = Field(default_factory=dict)
    active: bool = True

    @model_validator(mode="after")
    def _check(self) -> "PackIn":
        keys = [a.key for a in self.agents]
        if unknown := [k for k in keys if k not in FEATURES]:
            raise ValueError(f"unknown agents: {', '.join(unknown)}")
        if len(set(keys)) != len(keys):
            raise ValueError("an agent is listed twice")
        if wrong := [c for c, p in self.pricing.items() if p.currency != c]:
            raise ValueError(f"the price for {', '.join(wrong)} is in another currency")
        return self


def available(key: str) -> bool:
    return key in FEATURES and FEATURES[key].available and key in REGISTRY


def _row(r) -> dict:
    return {"key": r["key"], "name": r["name"], "tagline": r["tagline"], "audience": r["audience"], "agents": r["agents"],
            "pricing": r["pricing"], "active": r["active"], **({"clients": r["clients"]} if "clients" in r else {})}


async def list_packs(conn: AsyncConnection, *, active_only: bool = False) -> list[dict]:
    """conn: a system session (the client count reads every organisation's settings)."""
    rows = (await conn.execute(text("""select p.*, (select count(*) from app.org_settings s where s.agent_pack = p.key) as clients
        from app.agent_packs p where p.active or not :a order by p.active desc, p.name"""), {"a": active_only})).mappings().all()
    return [_row(r) for r in rows]


async def get_pack(conn: AsyncConnection, key: str) -> dict:
    r = (await conn.execute(text("select * from app.agent_packs where key = :k"), {"k": key})).mappings().first()
    if not r:
        raise PackError("no such pack")
    return _row(r)


async def save_pack(conn: AsyncConnection, key: str, body: PackIn, *, create: bool) -> dict:
    params = {"k": key, "n": body.name, "t": body.tagline, "au": body.audience, "ac": body.active,
              "ag": json.dumps([a.model_dump() for a in body.agents]),
              "pr": json.dumps({c: json.loads(p.model_dump_json()) for c, p in body.pricing.items()})}
    if create:
        done = (await conn.execute(text("""insert into app.agent_packs (key, name, tagline, audience, agents, pricing, active)
            values (:k, :n, :t, :au, cast(:ag as jsonb), cast(:pr as jsonb), :ac) on conflict (key) do nothing returning key"""), params)).first()
        if not done:
            raise PackError("a pack with this key already exists")
    else:
        done = (await conn.execute(text("""update app.agent_packs set name = :n, tagline = :t, audience = :au, agents = cast(:ag as jsonb),
            pricing = cast(:pr as jsonb), active = :ac, updated_at = now() where key = :k returning key"""), params)).first()
        if not done:
            raise PackError("no such pack")
    return await get_pack(conn, key)


async def _keys(conn: AsyncConnection) -> list[str]:
    return list((await conn.execute(text("select template_key from app.automation_instances order by 1"))).scalars())


async def assign(conn: AsyncConnection, org_id: str, pack_key: str, agents: list[str] | None, *, apply_pricing: bool,
                 staff_user_id: str) -> dict:
    """Give a client a pack (or change it, or retailor it). conn: the client's tenant session.

    agents: which of the pack's agents this client gets (None = the pack's defaults). The ones that are built are
    switched on (an already-live client gets them in approval mode); agents of the previous pack that aren't chosen any
    more are switched off; standalone add-ons are left alone."""
    pack = await get_pack(conn, pack_key)
    if not pack["active"]:
        raise PackError("this pack is archived")
    in_pack = [a["key"] for a in pack["agents"]]
    chosen = [a["key"] for a in pack["agents"] if a["default_on"]] if agents is None else list(dict.fromkeys(agents))
    if extra := [k for k in chosen if k not in in_pack]:
        raise PackError(f"not in the {pack['name']} pack: {', '.join(extra)}")
    on = [k for k in chosen if available(k)]
    if not on:
        raise PackError("none of the chosen agents can be switched on yet: choose at least one that is built")
    settings = (await conn.execute(text("select status, currency from app.org_settings"))).mappings().first()
    if not settings:
        raise PackError("this client isn't set up yet")
    status = "approval_mode" if settings["status"] == "live" else "setup"
    for k in on:
        await conn.execute(text("""insert into app.automation_instances (org_id, template_key, status, config, source)
            values (:o, :k, :s, cast(:c as jsonb), 'pack') on conflict (org_id, template_key) do update set source = 'pack'"""),
            {"o": org_id, "k": k, "s": status, "c": json.dumps(default_config(k))})
    await conn.execute(text("""delete from app.automation_instances where source = 'pack' and not (template_key = any(:on))"""), {"on": on})
    await conn.execute(text("update app.org_settings set agent_pack = :p, agent_pack_agents = cast(:a as jsonb)"),
                       {"p": pack_key, "a": json.dumps(chosen)})
    priced = False
    if apply_pricing and (plan := pack["pricing"].get(settings["currency"])):
        await billing.save_plan(conn, org_id, billing.PricingPlan(**plan))
        priced = True
    from agentry.clients import _add_steps  # clients imports this module
    features = for_automations(await _keys(conn))
    await _add_steps(conn, org_id, features["steps"])
    await audit.record(conn, org_id=org_id, actor_type="agentry_staff", actor_user_id=staff_user_id, action="pack.assigned",
                       target_type="pack", target_id=pack_key, metadata={"agents": chosen, "pricing": priced})
    return features


async def remove(conn: AsyncConnection, org_id: str, *, keep_agents: bool, staff_user_id: str) -> dict:
    """Take a client's pack away. Its agents stay as standalone add-ons, or are switched off."""
    pack = (await conn.execute(text("select agent_pack from app.org_settings"))).scalar_one_or_none()
    if not pack:
        raise PackError("this client has no pack")
    if keep_agents:
        await conn.execute(text("update app.automation_instances set source = 'standalone' where source = 'pack'"))
    else:
        left = (await conn.execute(text("select count(*) from app.automation_instances where source <> 'pack'"))).scalar_one()
        if left == 0:
            raise PackError("a client needs at least one automation: keep the agents or add one first")
        await conn.execute(text("delete from app.automation_instances where source = 'pack'"))
    await conn.execute(text("update app.org_settings set agent_pack = null, agent_pack_agents = '[]'"))
    await audit.record(conn, org_id=org_id, actor_type="agentry_staff", actor_user_id=staff_user_id, action="pack.removed",
                       target_type="pack", target_id=pack, metadata={"kept_agents": keep_agents})
    return for_automations(await _keys(conn))


async def org_pack(conn: AsyncConnection) -> dict | None:
    """The client's pack as they bought it: each chosen agent, whether it's on, and which are coming soon. conn: tenant."""
    from agentry.clients import NAMES
    s = (await conn.execute(text("""select s.agent_pack, s.agent_pack_agents, p.name, p.tagline from app.org_settings s
        left join app.agent_packs p on p.key = s.agent_pack"""))).mappings().first()
    if not s or not s["agent_pack"]:
        return None
    rows = dict((await conn.execute(text("select template_key, source from app.automation_instances"))).all())

    def name(k: str) -> str:
        return REGISTRY[k].name if k in REGISTRY else NAMES.get(k, (k, ""))[0]
    return {"key": s["agent_pack"], "name": s["name"], "tagline": s["tagline"],
            "agents": [{"key": k, "name": name(k), "on": k in rows, "coming_soon": not available(k)} for k in s["agent_pack_agents"]],
            "add_ons": [{"key": k, "name": name(k)} for k, src in sorted(rows.items()) if src == "standalone"]}

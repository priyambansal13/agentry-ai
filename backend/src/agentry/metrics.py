"""Metric registry (config/metrics.yaml) and the daily rollup that feeds every dashboard number."""
from functools import lru_cache

import yaml
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from agentry.config import BACKEND


@lru_cache
def registry() -> list[dict]:
    return yaml.safe_load((BACKEND / "config" / "metrics.yaml").read_text())["metrics"]


async def sync_definitions(conn: AsyncConnection) -> None:
    for m in registry():
        await conn.execute(
            text("""insert into app.metric_definitions (key, name, automation_key, event_type, aggregation, value_path, unit, higher_is_better)
                    values (:key, :name, :automation_key, :event_type, :aggregation, :value_path, :unit, :hib)
                    on conflict (key) do update set name = excluded.name, automation_key = excluded.automation_key,
                      event_type = excluded.event_type, aggregation = excluded.aggregation,
                      value_path = excluded.value_path, unit = excluded.unit, higher_is_better = excluded.higher_is_better"""),
            {**{k: m.get(k) for k in ("key", "name", "automation_key", "event_type", "aggregation", "value_path", "unit")},
             "hib": m.get("higher_is_better", True)},
        )


ROLLUP_SQL = """
insert into app.metrics_daily (org_id, metric_key, day, value, computed_at)
select e.org_id, d.key, (e.occurred_at at time zone s.timezone)::date as day,
       case when d.aggregation = 'count' then count(*)::numeric
            else coalesce(sum((e.payload ->> d.value_path)::numeric), 0) end,
       now()
from app.events e
join app.metric_definitions d on d.event_type = e.type
join app.org_settings s on s.org_id = e.org_id
where e.occurred_at >= now() - make_interval(days => :days)
group by e.org_id, d.key, d.aggregation, day
on conflict (org_id, metric_key, day) do update set value = excluded.value, computed_at = excluded.computed_at
"""


async def rollup(conn: AsyncConnection, days: int = 70) -> int:
    """Recompute the last `days` days for every organisation (system role: crosses tenants)."""
    result = await conn.execute(text(ROLLUP_SQL), {"days": days})
    return result.rowcount or 0

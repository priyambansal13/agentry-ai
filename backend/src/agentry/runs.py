"""Agent runs (ROADMAP-V2 §2.5): one unit of agent work, with its steps, model calls, cost and outcome.

    async with run(org_id, "inbox_triage", "triage.email", subject=("conversation", cid)) as r:
        ...                      # model calls inside are tagged with the run (llm/gateway.py reads current_run)
        r.step("classified", category="Lead")

Long jobs that span several durable workflow steps pass the same `key` from each step: the first creates the run,
the others re-open it, and `final=True` on the last one closes it. A run never breaks the work it records: if
recording fails, the work carries on.
"""
import contextvars
import json
import logging
import time
from contextlib import asynccontextmanager
from datetime import UTC, datetime

from sqlalchemy import text

from agentry.db import tenant_session

log = logging.getLogger(__name__)
current_run: contextvars.ContextVar[str | None] = contextvars.ContextVar("agentry_run", default=None)
_current_obj: contextvars.ContextVar["Run | None"] = contextvars.ContextVar("agentry_run_obj", default=None)


class Run:
    def __init__(self, org_id: str, run_id: str | None):
        self.org_id, self.id = org_id, run_id
        self._steps: list[dict] = []
        self._t = time.monotonic()
        self.error: str | None = None

    def fail(self, error: str) -> None:
        """The work handled its own error (e.g. returned "failed"): record the run as failed anyway."""
        self.error = error[:300]

    def step(self, name: str, **detail: object) -> None:
        now = time.monotonic()
        self._steps.append({"name": name, "at": datetime.now(UTC).isoformat(timespec="seconds"), "ms": int((now - self._t) * 1000),
                            **({"detail": {k: v for k, v in detail.items() if v is not None}} if detail else {})})
        self._t = now


async def _open(org_id: str, agent: str, kind: str, key: str | None, subject: tuple[str, str] | None) -> str | None:
    try:
        async with tenant_session(org_id) as conn:
            if key:
                rid = (await conn.execute(text("""insert into app.agent_runs (org_id, agent, kind, key, subject_type, subject_id)
                    values (:o, :a, :k, :key, :st, :si) on conflict (org_id, key) do update set status = 'running', ended_at = null
                    returning id::text"""), {"o": org_id, "a": agent, "k": kind, "key": key, "st": subject[0] if subject else None,
                                              "si": str(subject[1]) if subject else None})).scalar_one()
            else:
                rid = (await conn.execute(text("""insert into app.agent_runs (org_id, agent, kind, subject_type, subject_id)
                    values (:o, :a, :k, :st, :si) returning id::text"""), {"o": org_id, "a": agent, "k": kind,
                                                                        "st": subject[0] if subject else None,
                                                                        "si": str(subject[1]) if subject else None})).scalar_one()
        return rid
    except Exception:
        log.exception("couldn't open an agent run")
        return None


async def _close(r: Run, status: str | None, error: str | None) -> None:
    if not r.id:
        return
    try:
        async with tenant_session(r.org_id) as conn:
            await conn.execute(text("""update app.agent_runs ar set steps = ar.steps || cast(:s as jsonb),
                status = coalesce(:st, ar.status), error = coalesce(:e, ar.error),
                ended_at = case when :st is not null then now() else ar.ended_at end,
                model_calls = c.n, input_tokens = c.it, output_tokens = c.ot, cost_usd = c.cost
                from (select count(*) as n, coalesce(sum(input_tokens), 0) as it, coalesce(sum(output_tokens), 0) as ot,
                             coalesce(sum(cost_usd), 0) as cost from app.llm_calls where run_id = cast(:i as uuid)) c
                where ar.id = cast(:i as uuid)"""), {"s": json.dumps(r._steps, default=str), "st": status, "e": error, "i": r.id})
    except Exception:
        log.exception("couldn't close an agent run")


@asynccontextmanager
async def run(org_id: str, agent: str, kind: str, *, key: str | None = None, subject: tuple[str, str] | None = None, final: bool = True):
    """final=False: a step of a longer job (the run stays 'running' until a step with final=True ends it)."""
    rid = await _open(org_id, agent, kind, key, subject)
    r = Run(org_id, rid)
    token, token_obj = current_run.set(rid), _current_obj.set(r)
    try:
        yield r
    except Exception as e:
        await _close(r, "failed", f"{type(e).__name__}: {str(e)[:300]}")
        raise
    else:
        await _close(r, "failed" if r.error else ("ok" if final else None), r.error)
    finally:
        current_run.reset(token)
        _current_obj.reset(token_obj)


class _NoRun(Run):
    def __init__(self):
        super().__init__("", None)


def current() -> Run:
    """The run this code is inside (a do-nothing one outside any run), so code can record steps without checks."""
    return _current_obj.get() or _NoRun()


async def fail(org_id: str, key: str, error: str) -> None:
    """Mark a keyed run failed from outside (a workflow caught the error itself)."""
    async with tenant_session(org_id) as conn:
        await conn.execute(text("update app.agent_runs set status = 'failed', error = :e, ended_at = now() where key = :k"),
                           {"e": error[:300], "k": key})

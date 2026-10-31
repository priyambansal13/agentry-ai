"""`agentry` command-line tool (uv run agentry --help)."""
import asyncio
import json
from pathlib import Path

import typer

app = typer.Typer(help="Agentry platform tools", no_args_is_help=True)


@app.command()
def api(port: int = 8801, reload: bool = True, host: str = "127.0.0.1") -> None:
    """Run the HTTP API (containers: --host 0.0.0.0 --no-reload)."""
    import uvicorn
    uvicorn.run("agentry.api.main:app", host=host, port=port, reload=reload, proxy_headers=True, forwarded_allow_ips="*")


@app.command()
def voice() -> None:
    """Run the voice worker (LiveKit Agents): answers calls and browser test calls with the client's agent."""
    from agentry.voice.worker import main
    main()


@app.command()
def migrate() -> None:
    """Apply database migrations (alembic upgrade head) as the schema owner."""
    from alembic import command
    from alembic.config import Config

    from agentry.config import BACKEND
    cfg = Config(str(BACKEND / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND / "migrations"))
    command.upgrade(cfg, "head")
    from sqlalchemy import create_engine, text

    from agentry.config import settings
    with create_engine(settings.migrate_database_url).connect() as c:
        typer.echo(f"database at revision {c.execute(text('select version_num from app.alembic_version')).scalar_one()}")


@app.command()
def alerts(minutes: int = 10, dry_run: bool = False) -> None:
    """Check platform health (failed workflows, stuck outbox, model errors) and alert ops. Run every `minutes`."""
    from agentry.ops import check, send
    problems = asyncio.run(check(minutes))
    for p in problems:
        typer.echo(f"ALERT {p}")
    if problems and not dry_run:
        send(problems)
    if not problems:
        typer.echo("ok")


@app.command()
def worker() -> None:
    """Run the DBOS worker (outbox dispatch, metric rollups, event handlers)."""
    from agentry.worker.main import main
    main()


@app.command()
def seed() -> None:
    """Load mock-data/ into the demo organisations (run `pnpm seed:auth` first)."""
    from agentry.seed import seed as run
    asyncio.run(run())


@app.command("load-inbox")
def load_inbox(org_slug: str, file: Path = Path("../mock-data/inbox-triage/sharma-inbox.jsonl")) -> None:
    """Feed a JSONL mock inbox into an organisation (the worker then triages each email)."""
    import json as _json

    from sqlalchemy import text as _text

    from agentry.automations.inbox_triage.ingest import ingest_email
    from agentry.db import system_session

    async def run() -> None:
        async with system_session() as conn:
            org = (await conn.execute(_text("select id from auth.organization where slug = :s"), {"s": org_slug})).scalar_one()
        rows = [_json.loads(line) for line in file.read_text().splitlines() if line.strip()]
        for r in rows:
            await ingest_email(org, sender=r["from"], subject=r["subject"], body=r["body"], thread_ref=f"mock-{r['id']}",
                               received_at=r.get("at"))
        typer.echo(f"queued {len(rows)} emails for {org_slug}; the worker triages them within seconds")

    asyncio.run(run())


@app.command()
def reindex(org_slug: str | None = None) -> None:
    """Re-embed every knowledge chunk with the current embed model (run after changing AGENTRY_MODEL_EMBED)."""
    from sqlalchemy import text as _text

    from agentry.db import system_session
    from agentry.knowledge import _vec
    from agentry.llm.gateway import embed, models_for

    async def run() -> None:
        async with system_session() as conn:
            rows = (await conn.execute(_text("""select c.id, c.org_id, coalesce(d.title, '') || chr(10) || c.content as body
                from app.kb_chunks c join app.kb_documents d on d.id = c.document_id
                join auth.organization o on o.id = c.org_id where cast(:s as text) is null or o.slug = :s"""),
                {"s": org_slug})).all()
        model = (await models_for("embed")) or ["mock (hashed vectors)"]
        typer.echo(f"re-embedding {len(rows)} chunks with {model[0]}")
        for i in range(0, len(rows), 50):
            batch = rows[i:i + 50]
            vectors, _ = await embed([r.body for r in batch], record=False)
            async with system_session() as conn:
                for r, v in zip(batch, vectors, strict=True):
                    await conn.execute(_text("update app.kb_chunks set embedding = cast(:e as vector) where id = :id"),
                                       {"e": _vec(v), "id": r.id})
        typer.echo("done")

    asyncio.run(run())


@app.command()
def models(ping: bool = False) -> None:
    """List models your OpenAI / Gemini keys can use, the current tier chains, and optionally ping each tier."""
    from agentry.llm.gateway import TIERS, complete, embed, models_for
    from agentry.llm.providers import list_models

    async def run() -> None:
        for provider, items in (await list_models()).items():
            typer.secho(f"\n{provider}", bold=True)
            if isinstance(items, str):
                typer.echo(f"  {items}")
            else:
                for m in items:
                    typer.echo(f"  {m}")
        typer.secho("\ntier chains (primary first; models without a key are skipped)", bold=True)
        for tier in TIERS:
            chain = await models_for(tier)
            typer.echo(f"  {tier:13} {' -> '.join(chain) if chain else 'MOCK (nothing configured)'}")
            if ping and chain:
                try:
                    if tier == "embed":
                        await embed(["ping"], record=False)
                        typer.echo("                ok")
                    else:
                        r = await complete(tier, [{"role": "user", "content": "Reply with the word: ok"}], record=False)
                        note = f" (after failing: {', '.join(r.attempts)})" if r.attempts else ""
                        typer.echo(f"                {r.model}: {r.text.strip()[:40]!r} in {r.latency_ms} ms{note}")
                except Exception as e:  # noqa: BLE001 - report and continue with the next tier
                    typer.secho(f"                FAILED: {e}", fg="red")

    asyncio.run(run())


@app.command("eval")
def eval_cmd(prompt: str, dataset: Path, field: str = "label", version: str | None = None,
             min_accuracy: float | None = None, business: str = "a small business") -> None:
    """Run a prompt over a labelled dataset; fail if accuracy is below --min-accuracy.
    --field takes one key or several comma-separated (all must match)."""
    from agentry.llm.evals import run_eval
    report = asyncio.run(run_eval(prompt, dataset.resolve(), field=field, version=version,
                                  defaults={"business": business}))
    summary = {k: report[k] for k in ("prompt", "dataset", "models", "mock", "n", "accuracy", "field_accuracy",
                                      "cost_usd", "p50_latency_ms")}
    typer.echo(json.dumps(summary, indent=2))
    if report["mistakes"]:
        typer.echo("mistakes (expected -> got):")
        for pair, count in report["mistakes"]:
            typer.echo(f"  {count} x {pair}")
    if report["mock"]:
        typer.secho("MOCK MODE: no model configured for this tier (AGENTRY_MODEL_FAST); accuracy is not meaningful.",
                    fg="yellow")
    if min_accuracy is not None and report["accuracy"] < min_accuracy and not report["mock"]:
        raise typer.Exit(code=1)


@app.command("eval-gate")
def eval_gate(require_models: bool = False) -> None:
    """Every prompt in config/eval-gates.yaml must keep its accuracy on its labelled set (ROADMAP-V2 §2.2).
    Without a model configured the gate is skipped (or fails with --require-models, as in CI with keys)."""
    import yaml

    from agentry.config import BACKEND, ROOT
    from agentry.llm.evals import run_eval
    gates = yaml.safe_load((BACKEND / "config" / "eval-gates.yaml").read_text())["gates"]
    failed = []
    for g in gates:
        report = asyncio.run(run_eval(g["prompt"], (ROOT / g["dataset"]).resolve(), field=g.get("field", "label"),
                                      defaults={"business": g.get("business", "a small business")}))
        if report["mock"]:
            typer.secho(f"{g['prompt']}: SKIPPED (no model configured)", fg="yellow")
            if require_models:
                failed.append(g["prompt"])
            continue
        ok = report["accuracy"] >= g["min_accuracy"]
        typer.secho(f"{g['prompt']}: {report['accuracy']:.0%} on {report['n']} (needs {g['min_accuracy']:.0%})", fg="green" if ok else "red")
        if not ok:
            failed.append(g["prompt"])
    if failed:
        typer.secho(f"eval gate failed: {', '.join(failed)}", fg="red")
        raise typer.Exit(code=1)


if __name__ == "__main__":
    app()

"""Test-set runner: run a prompt over a labelled JSONL dataset and report accuracy, cost and latency.

Each dataset row provides the prompt's {{variables}} and an `expected` object; `field` names the key(s) compared
between the model output and `expected` (e.g. "label", or "category,urgent": a row passes only if all match).
Used in CI as a quality gate (--min-accuracy).
"""
import asyncio
import json
import time
from collections import Counter
from pathlib import Path

from agentry.config import ROOT
from agentry.llm.gateway import complete
from agentry.llm.prompts import load


async def run_eval(prompt_key: str, dataset: Path, field: str = "label", version: str | None = None,
                   concurrency: int = 4, defaults: dict | None = None) -> dict:
    prompt = load(prompt_key, version)
    fields = [f.strip() for f in field.split(",") if f.strip()]
    rows = [json.loads(line) for line in dataset.read_text().splitlines() if line.strip()]
    sem = asyncio.Semaphore(concurrency)

    async def one(row: dict) -> dict:
        async with sem:
            res = await complete(prompt.tier, prompt.render(**({**(defaults or {}), **row})),  # type: ignore[arg-type]
                                 prompt_key=prompt.key, prompt_version=prompt.version, json_output=prompt.json_output,
                                 mock_response=json.dumps({f: "other" for f in fields}), record=False)
        got = {f: (res.data or {}).get(f) for f in fields}
        want = {f: row["expected"][f] for f in fields}
        show = (lambda d: "/".join(str(d[f]) for f in fields))
        return {"id": row.get("id"), "expected": show(want), "got": show(got), "ok": got == want,
                "field_ok": {f: got[f] == want[f] for f in fields}, "mock": res.mock, "model": res.model,
                "cost_usd": res.cost_usd, "latency_ms": res.latency_ms}

    started = time.time()
    results = await asyncio.gather(*(one(r) for r in rows))
    correct = sum(r["ok"] for r in results)
    report = {
        "prompt": f"{prompt.key}/{prompt.version}",
        "dataset": str(dataset.relative_to(ROOT)) if dataset.is_relative_to(ROOT) else str(dataset),
        "mock": any(r["mock"] for r in results),
        "n": len(results),
        "accuracy": correct / len(results) if results else 0.0,
        "field_accuracy": {f: sum(r["field_ok"][f] for r in results) / len(results) for f in fields} if results else {},
        "models": sorted({r["model"] for r in results}),
        "cost_usd": round(sum(r["cost_usd"] for r in results), 6),
        "p50_latency_ms": sorted(r["latency_ms"] for r in results)[len(results) // 2] if results else 0,
        "mistakes": Counter(f"{r['expected']} -> {r['got']}" for r in results if not r["ok"]).most_common(),
        "results": results,
        "seconds": round(time.time() - started, 2),
    }
    out = ROOT / "eval-results"
    out.mkdir(exist_ok=True)
    (out / f"{prompt.key}-{prompt.version}-{int(started)}.json").write_text(json.dumps(report, indent=2))
    return report

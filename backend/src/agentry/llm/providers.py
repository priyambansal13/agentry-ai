"""Discover which models the configured provider keys can use (`agentry models`), so tier settings come from the
real accounts instead of remembered model names."""
import os

import httpx

from agentry.llm.gateway import PROVIDER_KEYS


async def list_models() -> dict[str, list[str] | str]:
    out: dict[str, list[str] | str] = {}
    async with httpx.AsyncClient(timeout=20) as client:
        if key := os.environ.get(PROVIDER_KEYS["openai"]):
            r = await client.get("https://api.openai.com/v1/models", headers={"Authorization": f"Bearer {key}"})
            out["openai"] = (sorted(f"openai/{m['id']}" for m in r.json().get("data", []))
                             if r.status_code == 200 else f"error {r.status_code}: {r.text[:200]}")
        else:
            out["openai"] = "no OPENAI_API_KEY in .env"
        if key := os.environ.get(PROVIDER_KEYS["gemini"]):
            models, page = [], None
            while True:
                r = await client.get("https://generativelanguage.googleapis.com/v1beta/models",
                                     params={"pageSize": 200, **({"pageToken": page} if page else {})},
                                     headers={"x-goog-api-key": key})
                if r.status_code != 200:
                    out["gemini"] = f"error {r.status_code}: {r.text[:200]}"
                    break
                body = r.json()
                for m in body.get("models", []):
                    methods = m.get("supportedGenerationMethods", [])
                    kind = "embed" if "embedContent" in methods else "chat" if "generateContent" in methods else None
                    if kind:
                        models.append(f"gemini/{m['name'].removeprefix('models/')}  [{kind}]")
                page = body.get("nextPageToken")
                if not page:
                    out["gemini"] = sorted(models)
                    break
        else:
            out["gemini"] = "no GEMINI_API_KEY in .env"
    return out

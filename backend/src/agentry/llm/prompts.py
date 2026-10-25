"""Prompt registry: versioned prompt files in backend/prompts/<key>/<version>.md.

File format: YAML front matter (key, version, tier, json_output, user template) + the system prompt as the body.
Placeholders are {{name}}. Prompt versions are stamped on every LLM call, so results can be traced to wording.
"""
import re
from dataclasses import dataclass
from functools import lru_cache

import yaml

from agentry.config import BACKEND

PROMPTS = BACKEND / "prompts"
_VAR = re.compile(r"\{\{\s*(\w+)\s*\}\}")


@dataclass(frozen=True)
class Prompt:
    key: str
    version: str
    tier: str
    json_output: bool
    system: str
    user: str
    description: str = ""

    def render(self, **vars: object) -> list[dict]:
        def value(name: str) -> str:
            v = vars.get(name, "")
            return ("yes" if v else "no") if isinstance(v, bool) else str(v)

        def fill(t: str) -> str:
            return _VAR.sub(lambda m: value(m.group(1)), t)
        return [{"role": "system", "content": fill(self.system)}, {"role": "user", "content": fill(self.user)}]


@lru_cache
def load(key: str, version: str | None = None) -> Prompt:
    folder = PROMPTS / key
    if not folder.is_dir():
        raise KeyError(f"unknown prompt {key}")
    path = folder / f"{version}.md" if version else max(folder.glob("v*.md"), key=lambda p: int(p.stem[1:]))
    raw = path.read_text()
    _, front, body = raw.split("---", 2)
    meta = yaml.safe_load(front)
    return Prompt(key=meta["key"], version=meta["version"], tier=meta["tier"], json_output=meta.get("json_output", False),
                  system=body.strip(), user=meta["user"], description=meta.get("description", ""))

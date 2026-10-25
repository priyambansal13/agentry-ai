"""Client roles and permissions, loaded from config/roles.json (shared with the dashboard)."""
import json
from functools import lru_cache

from agentry.config import ROOT


@lru_cache
def _roles() -> dict:
    return json.loads((ROOT / "config" / "roles.json").read_text())["roles"]


def can(role: str | None, resource: str, action: str) -> bool:
    if not role:
        return False
    roles = _roles()
    return any(action in roles.get(r.strip(), {}).get("permissions", {}).get(resource, []) for r in role.split(","))


def role_label(role: str) -> str:
    return _roles().get(role, {}).get("label", role)

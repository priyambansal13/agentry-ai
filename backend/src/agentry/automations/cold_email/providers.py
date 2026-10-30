"""Outside services cold email depends on, each behind a small interface with a mock.

    places   search businesses ("dental clinic" in "Pune")      mock: mock-data/cold-email/places-sample.jsonl
    sites    read a business's website (home, about, team...)   mock: the pages stored with each mock business
    finder   people and emails a finder knows at a domain       mock: the "finder" list of each mock business
    verifier is this address deliverable?                        mock: the "verify" map (anything else: unknown)

settings.cold_email_providers picks the set ("mock" today). Real providers (Google Places, Hunter, MillionVerifier)
arrive in 5.6 behind these same functions, so the pipeline and its tests don't change.
"""
import json
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Literal, Protocol

from agentry.config import ROOT, settings

Verdict = Literal["valid", "catch_all", "invalid", "unknown"]
MOCK_FILE = ROOT / "mock-data" / "cold-email" / "places-sample.jsonl"


@dataclass
class Business:
    place_id: str
    name: str
    website: str | None
    category: str | None = None
    rating: float | None = None
    reviews: int | None = None
    city: str | None = None
    address: str | None = None
    phone: str | None = None


@dataclass
class SitePage:
    url: str
    title: str
    text: str


@dataclass
class FoundPerson:
    email: str
    name: str | None = None
    role: str | None = None
    confidence: int = 0
    extra: dict = field(default_factory=dict)


class Providers(Protocol):
    async def search(self, query: str, city: str, limit: int) -> list[Business]: ...
    async def read_site(self, website: str) -> list[SitePage]: ...
    async def find_people(self, domain: str) -> list[FoundPerson]: ...
    async def verify(self, email: str) -> Verdict: ...


@lru_cache
def _mock_rows() -> tuple[dict, ...]:
    return tuple(json.loads(line) for line in MOCK_FILE.read_text().splitlines() if line.strip())


def _domain(url: str | None) -> str | None:
    if not url:
        return None
    host = url.split("://", 1)[-1].split("/", 1)[0].lower()
    return host.removeprefix("www.") or None


class MockProviders:
    """Deterministic, free, offline: the reference funnel (50 -> 49 -> 8) on a sample of Pune dental clinics."""

    async def search(self, query: str, city: str, limit: int) -> list[Business]:
        keep = ("place_id", "name", "website", "category", "rating", "reviews", "city", "address", "phone")
        return [Business(**{k: r.get(k) for k in keep}) for r in _mock_rows()][:limit]

    async def read_site(self, website: str) -> list[SitePage]:
        d = _domain(website)
        row = next((r for r in _mock_rows() if _domain(r.get("website")) == d), None)
        return [SitePage(**p) for p in row["pages"]] if row else []

    async def find_people(self, domain: str) -> list[FoundPerson]:
        row = next((r for r in _mock_rows() if _domain(r.get("website")) == domain), None)
        return [FoundPerson(**p) for p in row["finder"]] if row else []

    async def verify(self, email: str) -> Verdict:
        e = email.lower()
        for r in _mock_rows():
            if e in r["verify"]:
                return r["verify"][e]
        return "unknown"


def get() -> Providers:
    if settings.cold_email_providers == "mock":
        return MockProviders()
    raise RuntimeError(f"cold email providers '{settings.cold_email_providers}' aren't available yet (Phase 5.6)")


def mock_suppressed() -> list[str]:
    """Addresses the sample expects to be on the suppression list (seeded by tests and the demo setup)."""
    return [r["suppress"] for r in _mock_rows() if r.get("suppress")]

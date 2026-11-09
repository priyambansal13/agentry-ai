"""Sign in as each demo login and open every portal page; report anything that errors.

    uv run --project backend python infra/smoke/crawl_portal.py [--base http://localhost:3201] [--origin http://localhost:3201]

200 = opened; 404 = not part of that client's plan (hidden on purpose); 307 = redirected (e.g. a page only for owners);
500 or an error page = a bug. Exit code 1 if any page is broken.
"""
import argparse
import re
import sys
import time
from pathlib import Path

import httpx

PASSWORD = "agentry-demo-123"
LOGINS = [
    "owner@everyagent.example", "manager@everyagent.example", "frontdesk@everyagent.example", "finance@everyagent.example",
    "viewer@everyagent.example", "riya@sharmadigital.example", "accounts@sharmadigital.example", "neha@smilecraft.example",
    "frontdesk@smilecraft.example", "natarajan@kaverisupplies.example", "jordan@brightpath.example", "multi@agentry.dev", "admin@agentry.dev",
]
APP = Path(__file__).resolve().parents[2] / "apps/dashboard/src/app/(app)"
BROKEN = re.compile(r"Application error|Internal Server Error|__next_error__|This page couldn.t load|Unhandled Runtime Error")


def pages() -> list[str]:
    out = []
    for p in APP.rglob("page.tsx"):
        route = "/" + str(p.parent.relative_to(APP)).replace(".", "").strip("/")
        if "[" not in route:
            out.append(route.rstrip("/") or "/")
    return sorted(set(out))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://localhost:3201")
    ap.add_argument("--origin", default=None, help="Origin header for sign-in (BETTER_AUTH_URL), defaults to --base")
    ap.add_argument("--login", action="append", help="only these logins")
    a = ap.parse_args()
    routes, bad, summary = pages(), [], []
    for email in a.login or LOGINS:
        with httpx.Client(base_url=a.base, timeout=120, follow_redirects=False) as c:
            for _ in range(6):  # sign-in is rate limited (Better Auth): wait as told and retry
                r = c.post("/api/auth/sign-in/email", json={"email": email, "password": PASSWORD}, headers={"Origin": a.origin or a.base})
                if r.status_code != 429:
                    break
                time.sleep(int(r.headers.get("x-retry-after") or r.headers.get("retry-after") or 10) + 1)
            if r.status_code != 200:
                print(f"{email}: sign-in failed {r.status_code} {r.text[:120]}")
                bad.append((email, "sign-in", r.status_code))
                continue
            counts: dict[int, int] = {}
            for route in routes:
                if route.startswith("/hq") and email != "admin@agentry.dev":
                    continue
                r = c.get(route)
                code = r.status_code
                if code >= 500 or (code == 200 and BROKEN.search(r.text)):
                    bad.append((email, route, code))
                    print(f"  BROKEN {email} {route} -> {code}")
                counts[code] = counts.get(code, 0) + 1
            summary.append((email, counts))
    print()
    for email, counts in summary:
        print(f"{email:38} " + "  ".join(f"{k}: {v}" for k, v in sorted(counts.items())))
    print(f"\n{len(bad)} broken" if bad else "\nno broken pages")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())

# ADR 0002 — Better Auth (self-hosted) for logins, instead of Clerk

Date: 2026-10-24 · Status: accepted (implemented in Phase 0)

## Context

CLIENT-PORTAL.md proposed Clerk, with Better Auth as the fallback "if WhatsApp OTP or self-hosting is a must". Building Phase 0 made the choice concrete:
- Clerk needs an external account and API keys before anything runs locally, and charges per monthly active user.
- Indian clients will want **phone / WhatsApp OTP**, which is a custom flow either way.
- The agency model needs Agentry staff to create client organisations and act inside them, with every action audited.

## Decision

**Better Auth**, running inside the dashboard (Next.js) with its tables in our Postgres (schema `auth`, role `agentry_auth`):
- Plugins:
  - `organization`: client orgs, invitations, roles from `config/roles.json`
  - `admin`: Agentry staff via `user.role = admin`
  - `magicLink`
  - `jwt`
- The Python API verifies Better Auth's short-lived **EdDSA JWTs** against `/api/auth/jwks`. The JWT proves identity only. The organisation comes from the `X-Org-Id` header, and membership and role are read fresh from `auth.member` on every request.
- The API's database roles can read only `auth.user`, `auth.organization`, `auth.member` and `auth.invitation`. They can never read `auth.jwks` (private keys), `auth.account` (password hashes), `auth.session` or `auth.verification`. This is enforced by migration 0002 and covered by a test.

## Consequences

- There are no external accounts or keys needed for development, user data stays in our database, and there is no per-user cost.
- We own security updates for the auth library: track Better Auth releases.
- Phone/WhatsApp OTP will use Better Auth's `phone-number` plugin with our own SMS/WhatsApp sender (Phase 3).
- Creating a client organisation through Better Auth's API requires a signed-in session, so the seed script inserts organisations directly. The HQ "create client" flow (Phase 1) will run as a staff session.

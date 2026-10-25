-- Roles and schemas for Agentry (runs once, on first container start).
--   agentry_auth   owns schema "auth" (Better Auth tables: users, sessions, organizations, members, invitations)
--   agentry_app    the API's role for tenant requests: NO bypassrls, so row-level security always applies
--   agentry_system workers + platform jobs (outbox dispatch, rollups, Agentry HQ): bypassrls
-- Schema "app" is owned by postgres (migrations run as postgres); DBOS keeps its state in schema "dbos".

CREATE ROLE agentry_auth   LOGIN PASSWORD 'agentry_auth';
CREATE ROLE agentry_app    LOGIN PASSWORD 'agentry_app';
CREATE ROLE agentry_system LOGIN PASSWORD 'agentry_system' BYPASSRLS;

CREATE SCHEMA auth AUTHORIZATION agentry_auth;
ALTER ROLE agentry_auth SET search_path = auth;

CREATE SCHEMA app;
GRANT USAGE ON SCHEMA app TO agentry_app, agentry_system;
GRANT USAGE ON SCHEMA auth TO agentry_app, agentry_system;
-- Better Auth creates its tables later (pnpm auth:migrate). Migration 0002 grants read access to the
-- non-secret ones only (user, organization, member, invitation), never jwks, account, session or verification.

CREATE SCHEMA dbos AUTHORIZATION agentry_system;
GRANT CREATE ON DATABASE agentry TO agentry_system;

CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pgcrypto;

#!/bin/sh
# Production variant of infra/postgres/init.sql (used by docker-compose.prod.yml and k3s): role passwords come from the environment (Kubernetes Secret / compose env).
set -eu
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<SQL
CREATE ROLE agentry_auth   LOGIN PASSWORD '${AGENTRY_DB_AUTH_PASSWORD}';
CREATE ROLE agentry_app    LOGIN PASSWORD '${AGENTRY_DB_APP_PASSWORD}';
CREATE ROLE agentry_system LOGIN PASSWORD '${AGENTRY_DB_SYSTEM_PASSWORD}' BYPASSRLS;
CREATE SCHEMA auth AUTHORIZATION agentry_auth;
ALTER ROLE agentry_auth SET search_path = auth;
CREATE SCHEMA app;
GRANT USAGE ON SCHEMA app TO agentry_app, agentry_system;
GRANT USAGE ON SCHEMA auth TO agentry_app, agentry_system;
CREATE SCHEMA dbos AUTHORIZATION agentry_system;
GRANT CREATE ON DATABASE ${POSTGRES_DB} TO agentry_system;
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pgcrypto;
SQL

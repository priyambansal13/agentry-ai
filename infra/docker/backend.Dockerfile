# Agentry backend: one image, four roles (api | worker | voice | jobs: migrate, alerts, reindex).
#   docker build -f infra/docker/backend.Dockerfile -t agentry-backend .
FROM python:3.12-slim AS build
COPY --from=ghcr.io/astral-sh/uv:0.9 /uv /bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PROJECT_ENVIRONMENT=/srv/.venv UV_PYTHON_DOWNLOADS=never
WORKDIR /srv/backend
COPY backend/pyproject.toml backend/uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv uv sync --frozen --no-dev --no-install-project
COPY backend/ ./
RUN --mount=type=cache,target=/root/.cache/uv uv sync --frozen --no-dev

FROM python:3.12-slim
RUN useradd --uid 10001 --create-home agentry
# Paths mirror the repo (config.ROOT = /srv): backend code, packs, prompts, migrations + the shared config/roles.json.
COPY --from=build --chown=agentry /srv /srv
COPY --chown=agentry config /srv/config
ENV PATH=/srv/.venv/bin:$PATH PYTHONUNBUFFERED=1 AGENTRY_ENV=production
# call recordings: a volume shared by voice (writes), api (serves) and worker (retention clean-up)
RUN mkdir -p /srv/var/recordings && chown -R agentry /srv/var
WORKDIR /srv/backend
USER agentry
EXPOSE 8801
CMD ["agentry", "api", "--host", "0.0.0.0", "--no-reload"]

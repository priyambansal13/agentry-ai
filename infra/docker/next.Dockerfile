# Agentry Next.js apps. One Dockerfile, two apps:
#   docker build -f infra/docker/next.Dockerfile --build-arg APP=dashboard -t agentry-dashboard .
#   docker build -f infra/docker/next.Dockerfile --build-arg APP=web -t agentry-web .
#   docker build -f infra/docker/next.Dockerfile --target tools -t agentry-dashboard-tools .   (auth:migrate, seed:auth)
# NEXT_PUBLIC_* values are compiled into the browser bundle, so they are build arguments.
FROM node:22-slim AS deps
RUN npm install -g pnpm@12.11.2
WORKDIR /repo
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
COPY apps/web/package.json apps/web/
COPY apps/dashboard/package.json apps/dashboard/
COPY apps/widget/package.json apps/widget/
COPY packages/ui/package.json packages/ui/
RUN --mount=type=cache,target=/root/.local/share/pnpm/store pnpm install --frozen-lockfile

FROM deps AS build
ARG APP=dashboard
ARG NEXT_PUBLIC_API_URL
ARG NEXT_PUBLIC_DASHBOARD_URL
ARG NEXT_PUBLIC_WEB_URL
ENV NEXT_TELEMETRY_DISABLED=1
COPY . .
RUN pnpm --filter @agentry/widget build && pnpm --filter @agentry/${APP} build

# Database jobs for the dashboard (Better Auth schema migration, first admin user).
FROM build AS tools
WORKDIR /repo/apps/dashboard
CMD ["pnpm", "exec", "tsx", "scripts/auth-migrate.ts"]

FROM node:22-slim AS runtime
ARG APP=dashboard
ENV NODE_ENV=production NEXT_TELEMETRY_DISABLED=1 HOSTNAME=0.0.0.0 PORT=3000 APP=${APP}
WORKDIR /app
COPY --from=build --chown=node /repo/apps/${APP}/.next/standalone ./
COPY --from=build --chown=node /repo/apps/${APP}/.next/static ./apps/${APP}/.next/static
COPY --from=build --chown=node /repo/apps/${APP}/public ./apps/${APP}/public
USER node
EXPOSE 3000
CMD ["sh", "-c", "exec node apps/$APP/server.js"]

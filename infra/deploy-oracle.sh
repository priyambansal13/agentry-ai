#!/bin/bash
# Update the live server (agentry-ai-oci) from this Mac: build arm64 images, copy them over, restart.
#   infra/deploy-oracle.sh            # everything
#   infra/deploy-oracle.sh backend    # only api / worker / migrations (most backend changes)
# Needs: Docker and rsync on the Mac, ~/.ssh/agentry-oci.key, and infra/.env.server (git-ignored) for the build's public URLs.
set -euo pipefail
cd "$(dirname "$0")/.."
HOST=${AGENTRY_HOST:-ubuntu@137.23.54.225}
KEY=${AGENTRY_SSH_KEY:-$HOME/.ssh/agentry-oci.key}
# a stalled connection fails in ~3 minutes instead of hanging the deploy
SSH_OPTS="-o ServerAliveInterval=30 -o ServerAliveCountMax=6 -o ConnectTimeout=20"
TAG=$(git rev-parse --short HEAD)
WHAT=${1:-all}
export AGENTRY_TAG=$TAG NEXT_PUBLIC_API_URL=https://api.agentry.duckdns.org NEXT_PUBLIC_DASHBOARD_URL=https://app.agentry.duckdns.org \
       NEXT_PUBLIC_WEB_URL=https://agentry.duckdns.org
# build with the base file only: docker-compose.server.yml turns building off (the server only loads images)
BUILD="docker compose -f docker-compose.prod.yml"
if [ "$WHAT" = backend ]; then SERVICES="api"; IMAGES="agentry-backend"; else SERVICES="api auth-migrate dashboard web"
  IMAGES="agentry-backend agentry-dashboard-tools agentry-dashboard agentry-web"; fi
echo "building $IMAGES at $TAG"
$BUILD --env-file infra/.env.server build $SERVICES
for img in $IMAGES; do docker image inspect "$img:$TAG" >/dev/null || { echo "missing $img:$TAG after the build"; exit 1; }; done
# each image is saved to a file and uploaded with rsync, which resumes after a dropped connection (a 2 GB stream
# over a flaky link kept failing part-way), then loaded on the server
OUT=$(mktemp -d)
trap 'rm -rf "$OUT"' EXIT
ssh $SSH_OPTS -i "$KEY" "$HOST" 'mkdir -p ~/agentry/images'
for img in $IMAGES; do
  f="$OUT/$img-$TAG.tar.gz"
  echo "copying $img"
  docker save "$img:$TAG" | gzip -1 > "$f"
  for try in 1 2 3 4 5 6 7 8 9 10; do
    rsync -a --partial --inplace --timeout=60 -e "ssh $SSH_OPTS -i $KEY" "$f" "$HOST:agentry/images/" && break
    echo "upload interrupted, resuming ($try)"; sleep 5
    [ "$try" = 10 ] && { echo "upload of $img failed"; exit 1; }
  done
  ssh $SSH_OPTS -i "$KEY" "$HOST" "gunzip -c ~/agentry/images/$(basename "$f") | sudo docker load && rm ~/agentry/images/$(basename "$f")"
  rm -f "$f"
done
if [ "$WHAT" = backend ]; then
  # one version number for every service: the unchanged portal and website images get the new tag too
  ssh $SSH_OPTS -i "$KEY" "$HOST" "OLD=\$(grep '^AGENTRY_TAG=' ~/agentry/infra/.env.prod | cut -d= -f2) && for img in agentry-dashboard agentry-dashboard-tools agentry-web; do sudo docker tag \$img:\$OLD \$img:$TAG; done"
fi
scp -i "$KEY" -q docker-compose.prod.yml docker-compose.server.yml "$HOST:agentry/"
scp -i "$KEY" -q infra/caddy/Caddyfile "$HOST:agentry/infra/caddy/"
# keep only this version and the one before it (for a rollback): each version is ~5 GB and the server disk is 45 GB
# AGENTRY_DEPLOYED_AT: shown to Agentry staff in the portal's sidebar (GET /hq/version)
ssh $SSH_OPTS -i "$KEY" "$HOST" "cd ~/agentry && PREV=\$(grep '^AGENTRY_TAG=' infra/.env.prod | cut -d= -f2) && sed -i 's/^AGENTRY_TAG=.*/AGENTRY_TAG=$TAG/' infra/.env.prod && \
  sed -i '/^AGENTRY_DEPLOYED_AT=/d' infra/.env.prod && echo AGENTRY_DEPLOYED_AT=\$(date -u +%Y-%m-%dT%H:%M:%SZ) >> infra/.env.prod && \
  sudo docker compose -p agentry -f docker-compose.prod.yml -f docker-compose.server.yml --env-file infra/.env.prod up -d && \
  for t in \$(sudo docker images --format '{{.Repository}}:{{.Tag}}' | grep -E '^agentry-(backend|dashboard|dashboard-tools|web):' | grep -vE \":($TAG|\$PREV)\$\"); do sudo docker rmi \$t >/dev/null 2>&1 || true; done && \
  sudo docker image prune -f >/dev/null && df -h / | tail -1 && sudo docker compose -p agentry -f docker-compose.prod.yml -f docker-compose.server.yml --env-file infra/.env.prod ps"
# and locally: Docker Desktop keeps every build too (the Mac disk filled up on 2026-11-12)
for t in $(docker images --format '{{.Repository}}:{{.Tag}}' | grep -E '^agentry-(backend|dashboard|dashboard-tools|web):' | grep -vE ":($TAG|local)$"); do docker rmi "$t" >/dev/null 2>&1 || true; done
echo "deployed $TAG: https://app.agentry.duckdns.org"

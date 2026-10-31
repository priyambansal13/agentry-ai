#!/bin/bash
# Update the live server (agentry-ai-oci) from this Mac: build arm64 images, copy them over, restart.
#   infra/deploy-oracle.sh            # everything
#   infra/deploy-oracle.sh backend    # only api / worker / migrations (most backend changes)
# Needs: Docker on the Mac, ~/.ssh/agentry-oci.key, and infra/.env.server (git-ignored) for the build's public URLs.
set -euo pipefail
cd "$(dirname "$0")/.."
HOST=${AGENTRY_HOST:-ubuntu@137.23.54.225}
KEY=${AGENTRY_SSH_KEY:-$HOME/.ssh/agentry-oci.key}
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
for img in $IMAGES; do
  echo "copying $img"
  docker save "$img:$TAG" | gzip -1 | ssh -i "$KEY" "$HOST" 'gunzip | sudo docker load'
done
if [ "$WHAT" = backend ]; then
  # one version number for every service: the unchanged portal and website images get the new tag too
  ssh -i "$KEY" "$HOST" "OLD=\$(grep '^AGENTRY_TAG=' ~/agentry/infra/.env.prod | cut -d= -f2) && for img in agentry-dashboard agentry-dashboard-tools agentry-web; do sudo docker tag \$img:\$OLD \$img:$TAG; done"
fi
scp -i "$KEY" -q docker-compose.prod.yml docker-compose.server.yml "$HOST:agentry/"
scp -i "$KEY" -q infra/caddy/Caddyfile "$HOST:agentry/infra/caddy/"
ssh -i "$KEY" "$HOST" "cd ~/agentry && sed -i 's/^AGENTRY_TAG=.*/AGENTRY_TAG=$TAG/' infra/.env.prod && \
  sudo docker compose -p agentry -f docker-compose.prod.yml -f docker-compose.server.yml --env-file infra/.env.prod up -d && \
  sudo docker image prune -f >/dev/null && sudo docker compose -p agentry -f docker-compose.prod.yml -f docker-compose.server.yml --env-file infra/.env.prod ps"
echo "deployed $TAG: https://app.agentry.duckdns.org"

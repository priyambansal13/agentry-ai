#!/usr/bin/env bash
# Deploy a release to the current kubectl context:  infra/k8s/deploy.sh <tag>
# Images must already be pushed (see docs/DEPLOY.md: "Build and push").
set -euo pipefail
cd "$(dirname "$0")"
TAG="${1:?usage: deploy.sh <image tag>}"
[ -f agentry.env ] || { echo "missing infra/k8s/agentry.env (copy infra/prod.env.example)"; exit 1; }
kustomize_out=$(mktemp)
kubectl kustomize . | sed "s#\(ghcr.io/[^:]*\):latest#\1:${TAG}#g" > "$kustomize_out"
kubectl apply -f "$kustomize_out" --dry-run=server >/dev/null
# Jobs are immutable: replace the migration job, wait for it, then roll the apps.
kubectl -n agentry delete job migrate --ignore-not-found
kubectl apply -f "$kustomize_out"
kubectl -n agentry wait --for=condition=complete job/migrate --timeout=300s
for d in api worker dashboard web; do kubectl -n agentry rollout status deploy/$d --timeout=300s; done
rm -f "$kustomize_out"
echo "deployed $TAG"

# Deploying Agentry

> **Target:** one Oracle Cloud **Ampere A1** VM (arm64; the Always Free shape has 4 OCPU / 24 GB) running **k3s**. Everything runs on it: Postgres, the API, the worker, the dashboard and the website.
> **Before a release:** verify the same images locally with `docker-compose.prod.yml` (§7).

## 1. What runs

| Workload | Image | Kind | Notes |
|---|---|---|---|
| `postgres` | `pgvector/pgvector:pg16` | StatefulSet, 20 Gi | Role passwords come from the secret on **first start of an empty volume** (`infra/k8s/postgres-init.sh`) |
| `migrate` | `agentry-dashboard-tools`, then `agentry-backend` | Job, every release | Better Auth tables first, then `agentry migrate` (Alembic). Both are idempotent. |
| `api` | `agentry-backend` | Deployment | Probes: `/health` (liveness), `/ready` (database reachable) |
| `worker` | `agentry-backend` | Deployment, **1 replica**, `Recreate` | DBOS: outbox, sequences, monthly statements, watchdog, rollups, call summaries, recording clean-up |
| `voice` (optional) | `agentry-backend` | Deployment | `agentry voice`: LiveKit Agents worker, one room per call. Off until LiveKit is configured (§5, Voice) |
| `recordings` | — | PVC, 20 Gi | Call recordings, shared by `voice` (writes), `api` (serves) and `worker` (deletes after each client's retention). Single-node only: move to Object Storage before adding nodes |
| `dashboard` | `agentry-dashboard` | Deployment | Client portal + Agentry HQ + Better Auth (`/api/auth/*`) |
| `web` | `agentry-web` | Deployment | Landing page, `/demo/[slug]`, `widget.js` |
| `backup` | `pgvector/pgvector:pg16` | CronJob 03:00 IST | `pg_dump -Fc`, checked with `pg_restore --list`, kept 14 days on PVC `backups` |
| `alerts` | `agentry-backend` | CronJob every 10 min | `agentry alerts`: failed workflows, stuck outbox (worker down), model error rate > 25 %, broken connections (hourly) → `AGENTRY_OPS_EMAIL` and Telegram |

Ingress (Traefik, bundled with k3s) maps three hostnames:
- `agentry.example` → web
- `app.agentry.example` → dashboard
- `api.agentry.example` → API, which also receives the OAuth callbacks and the Gmail, WhatsApp, Razorpay and Stripe webhooks

## 2. One-time server setup

1. **Create the VM:** Ubuntu 24.04, shape `VM.Standard.A1.Flex` (4 OCPU / 24 GB), with a 100 GB boot volume.
2. **Open ports 80 and 443:**
   - In the VCN security list, add ingress rules for TCP 80 and 443.
   - Oracle's Ubuntu images also block these ports in iptables:
     ```bash
     sudo iptables -I INPUT 6 -p tcp --dport 80 -j ACCEPT
     sudo iptables -I INPUT 6 -p tcp --dport 443 -j ACCEPT
     sudo netfilter-persistent save
     ```
3. **Install k3s:**
   ```bash
   curl -sfL https://get.k3s.io | sh -
   sudo cat /etc/rancher/k3s/k3s.yaml   # copy to your laptop as ~/.kube/agentry.yaml; set server: https://<VM IP>:6443
   ```
   To use kubectl from your laptop, open TCP 6443 for your own IP only, or use an SSH tunnel: `ssh -L 6443:localhost:6443 ubuntu@<VM IP>`.
4. **DNS:** point A records for `agentry.example`, `app.agentry.example` and `api.agentry.example` at the VM's public IP.
5. **TLS (Let's Encrypt):**
   ```bash
   kubectl apply -f https://github.com/cert-manager/cert-manager/releases/latest/download/cert-manager.yaml
   kubectl apply -f - <<'EOF'
   apiVersion: cert-manager.io/v1
   kind: ClusterIssuer
   metadata: { name: letsencrypt }
   spec:
     acme:
       server: https://acme-v02.api.letsencrypt.org/directory
       email: you@agentry.example
       privateKeySecretRef: { name: letsencrypt-account }
       solvers: [{ http01: { ingress: { ingressClassName: traefik } } }]
   EOF
   ```

## 3. Configure

1. **Copy the env template:** `cp infra/prod.env.example infra/k8s/agentry.env` (the copy is gitignored), then fill it in:
   - Generate every password and secret fresh (the template shows how).
   - `AGENTRY_ENCRYPTION_KEY` encrypts stored Gmail/WhatsApp tokens. **Back it up separately: without it, every stored connection has to be redone.**
   - SMTP: use any provider with a login (Amazon SES, Zoho, Brevo …). Magic-link sign-in and invitations depend on it.
   - Model keys and tiers: the same values as your dev `.env` (Gemini first, OpenAI fallback).
2. **Domains:** replace `agentry.example` in `infra/k8s/ingress.yaml`, and in `agentry.env` (URLs and CORS origins).
3. **Images:** in `infra/k8s/kustomization.yaml`, set `YOUR_GITHUB_USER` (or another registry).

## 4. Build and push

The Ampere VM is arm64. An Apple-silicon Mac builds arm64 natively. From Intel or CI, add `--platform linux/arm64`.

```bash
TAG=$(date +%Y%m%d-%H%M)
REG=ghcr.io/YOUR_GITHUB_USER
PUBLIC="--build-arg NEXT_PUBLIC_API_URL=https://api.agentry.example --build-arg NEXT_PUBLIC_DASHBOARD_URL=https://app.agentry.example --build-arg NEXT_PUBLIC_WEB_URL=https://agentry.example"

docker build -f infra/docker/backend.Dockerfile -t $REG/agentry-backend:$TAG .
docker build -f infra/docker/next.Dockerfile --build-arg APP=dashboard $PUBLIC -t $REG/agentry-dashboard:$TAG .
docker build -f infra/docker/next.Dockerfile --build-arg APP=dashboard --target tools -t $REG/agentry-dashboard-tools:$TAG .
docker build -f infra/docker/next.Dockerfile --build-arg APP=web $PUBLIC -t $REG/agentry-web:$TAG .
echo $GITHUB_TOKEN | docker login ghcr.io -u YOUR_GITHUB_USER --password-stdin
for i in backend dashboard dashboard-tools web; do docker push $REG/agentry-$i:$TAG; done
```

`NEXT_PUBLIC_*` values are compiled into the browser bundle, so a domain change needs a rebuild.

**Private packages:** let the cluster pull them with a pull secret.

```bash
kubectl create namespace agentry
kubectl -n agentry create secret docker-registry ghcr --docker-server=ghcr.io --docker-username=YOUR_GITHUB_USER --docker-password=$GITHUB_TOKEN
kubectl -n agentry patch serviceaccount default -p '{"imagePullSecrets":[{"name":"ghcr"}]}'
```

**Without a registry:** copy each image straight to the node:

```bash
docker save $REG/agentry-backend:$TAG | ssh ubuntu@<VM IP> sudo k3s ctr images import -
```

## 5. Deploy

```bash
export KUBECONFIG=~/.kube/agentry.yaml
infra/k8s/deploy.sh $TAG
```

The script does the following:
1. Renders the manifests and pins the release's image tag.
2. Validates them against the cluster.
3. Re-creates the `migrate` Job and waits for it to finish.
4. Waits for every rollout.

**First deploy only: create your admin login.** Follow the three commands at the top of `infra/k8s/one-off/create-admin.yaml`. The Job prints a one-time password. Sign in at `https://app.agentry.example` (or use an emailed magic link), then create client organisations from Agentry HQ.

**Webhooks to register** (all on `https://api.agentry.example`):

| Provider | Endpoint |
|---|---|
| Gmail OAuth redirect | `/connect/google/callback` (see `docs/setup/gmail.md`) |
| WhatsApp | `/webhooks/whatsapp` (see `docs/setup/whatsapp.md`) |
| Clients' Razorpay / Stripe (invoice payments) | `/webhooks/razorpay/{connection_id}`, `/webhooks/stripe/{connection_id}` (shown on each client's connection card) |
| Agentry's own billing | `/webhooks/billing/razorpay` (event `payment_link.paid`), `/webhooks/billing/stripe` (event `checkout.session.completed`) |

**Voice (calls).** Off by default. To switch it on:
1. Create a LiveKit Cloud project (free tier to start), or run your own LiveKit server.
2. Fill `AGENTRY_LIVEKIT_URL`, `AGENTRY_LIVEKIT_PUBLIC_URL`, `AGENTRY_LIVEKIT_API_KEY` and `AGENTRY_LIVEKIT_API_SECRET` in `agentry.env`. `OPENAI_API_KEY` is also used for speech.
3. Uncomment `voice.yaml` in `infra/k8s/kustomization.yaml` and re-run `deploy.sh`.

With Docker Compose, use `--profile voice`. Phone numbers (SIP) come with milestone 4.3.

## 6. Operate

| Task | Command |
|---|---|
| Status | `kubectl -n agentry get pods,cronjobs` |
| Logs | `kubectl -n agentry logs deploy/worker -f` (also `deploy/api`) |
| Health check now | `kubectl -n agentry create job --from=cronjob/alerts alerts-now && kubectl -n agentry logs job/alerts-now -f` |
| Backup now | `kubectl -n agentry create job --from=cronjob/backup backup-now` |
| Copy backups off the VM | `kubectl -n agentry cp <backup pod>:/backups ./backups` (also put a copy in Object Storage weekly: a VM-only backup dies with the VM) |
| Restore | Scale `api`, `worker` and `dashboard` to 0, then `pg_restore --clean --if-exists -d agentry <file>` from a `pgvector` pod, then scale back to 1 |
| Rollback | `infra/k8s/deploy.sh <previous tag>` (migrations only add things, so older code keeps working) |
| Rotate a secret | Edit `agentry.env`, re-run `deploy.sh` (the secret's name hash changes, so the pods restart) |

## 7. Verify a release locally first

The same images, with production settings, on your laptop:

```bash
cp infra/prod.env.example infra/.env.prod    # or keep the generated local one: random secrets, mock models, dev Mailpit
docker compose -p agentry-prod -f docker-compose.prod.yml --env-file infra/.env.prod up -d --build
```

| Service | URL |
|---|---|
| Web | http://localhost:13200 |
| Dashboard | http://localhost:13201 |
| API | http://localhost:18801/ready |

Run the jobs by hand:
- `... run --rm alerts`
- `... run --rm backup`

**Stop:** `docker compose -p agentry-prod -f docker-compose.prod.yml down`. Add `-v` to also delete its database.

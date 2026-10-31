# Agentry on Oracle Cloud (live)

| | |
|---|---|
| Server | `agentry-ai-oci` (Ampere A1, 2 OCPU / 12 GB, Ubuntu 24.04 arm64), public IP **137.23.54.225**, Mumbai |
| SSH | `ssh -i ~/.ssh/agentry-oci.key ubuntu@137.23.54.225` (key from the Oracle console, copied from Downloads) |
| Sites | https://agentry.duckdns.org (landing) · https://app.agentry.duckdns.org (portal) · https://api.agentry.duckdns.org (API, webhooks, widget) |
| DNS | DuckDNS `agentry` → 137.23.54.225; `app.` and `api.` follow automatically |
| HTTPS | Caddy in the stack (`infra/caddy/Caddyfile`), Let's Encrypt, renews itself |
| Firewall | Oracle security list: 22, 80, 443 open. The Ubuntu image's own iptables also needed 80/443 (added and saved) |
| Files on the server | `~/agentry/`: the two compose files, `infra/.env.prod` (secrets, mode 600; the Mac's git-ignored `infra/.env.server`), `infra/caddy/Caddyfile`, `infra/k8s/postgres-init.sh` |

Started 2026-10-31 with a fresh database: admin `pbansal.agentry@gmail.com` and the Agentry company (landing chat "Ava",
website chat live). Client companies are added from HQ.

## Update after code changes

```sh
infra/deploy-oracle.sh            # everything (about 10 min: images are built on the Mac and copied over)
infra/deploy-oracle.sh backend    # only API/worker/migrations
```
Images are built on the Mac (also arm64), so the server never compiles anything. Migrations (`agentry migrate`,
including the chat agents' checkpoint tables) run automatically on every start.

## Everyday commands (on the server)

```sh
cd ~/agentry
C="sudo docker compose -p agentry -f docker-compose.prod.yml -f docker-compose.server.yml --env-file infra/.env.prod"
$C ps                       # what's running
$C logs -f --tail 100 worker  # or api, dashboard, web, caddy
$C restart worker
$C exec api agentry alerts --dry-run   # health checks
```

## Backups (you install this once)

Nightly database dump to `~/agentry-backups/` at 02:30 server time. On the server run `crontab -e` and add one line:

```
30 2 * * * cd /home/ubuntu/agentry && sudo docker compose -p agentry -f docker-compose.prod.yml -f docker-compose.server.yml --env-file infra/.env.prod --profile jobs run --rm -T backup >> /home/ubuntu/agentry-backups/backup.log 2>&1 && find /home/ubuntu/agentry-backups -name 'agentry-*.dump' -mtime +14 -delete
```

Copy dumps off the server now and then (`scp -i ~/.ssh/agentry-oci.key 'ubuntu@137.23.54.225:agentry-backups/*.dump' .`).

## External services to point at the live URLs

| Service | Set to |
|---|---|
| Google OAuth client (Gmail connect) | add authorised redirect URI `https://api.agentry.duckdns.org/connect/google/callback` |
| Meta WhatsApp webhook | `https://api.agentry.duckdns.org/webhooks/whatsapp`, verify token = `AGENTRY_WHATSAPP_VERIFY_TOKEN` |
| Razorpay webhook (per client connection) | `https://api.agentry.duckdns.org/webhooks/razorpay/<connection id>` |
| Outlook (optional) | redirect URI `https://api.agentry.duckdns.org/connect/microsoft/callback` |
| Telegram | automatic: with `AGENTRY_TELEGRAM_BOT_TOKEN` set, the worker registers the webhook on start |

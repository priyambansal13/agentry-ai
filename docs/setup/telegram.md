# Setting up Telegram

Agentry uses two kinds of Telegram bot:

| Bot | Who creates it | What it's for |
|---|---|---|
| **Agentry's team bot** (one, for all clients) | Agentry, once | Owners and staff get alerts and Needs-you cards with Approve / Edit / Discard buttons, and a **Tools** menu for every agent |
| **A business's own bot** (one per client) | The client (or Agentry for them) | The client's customers chat with the AI assistant on Telegram, like WhatsApp |

## 1. Agentry's team bot (once)

1. In Telegram, open **@BotFather** → `/newbot` → name it e.g. *Agentry* and a username like `agentry_team_bot`.
2. Copy the token into `.env`: `AGENTRY_TELEGRAM_BOT_TOKEN=123456:AA…`
3. Optional, in BotFather → `/setcommands`:
   ```
   tools - Everything your agents do
   needs - What needs you right now
   business - Switch business
   help - What I can do
   ```
4. Restart the API and worker.

Each person then links their own Telegram from **Account & notifications → Telegram → Connect Telegram**.
This opens the bot with a one-time code, valid for 15 minutes. After that, Telegram appears as a channel in their
notification table, plus a "cards" row (Telegram only).

## 2. A business's own bot (per client)

1. The client opens **@BotFather** → `/newbot` with their business name, e.g. `smilecraft_bot`.
2. In Agentry: **Connections → Telegram**, paste the token. Agentry checks it with Telegram and switches on the
   *Telegram assistant* (approval mode first, like WhatsApp).
3. Share `https://t.me/<their_bot>` on the website, Google profile and visiting cards.

Telegram bots can only **reply** to people who wrote first: no cold messages or reminders on Telegram.

## How messages reach Agentry

| `AGENTRY_TELEGRAM_MODE` | When | How |
|---|---|---|
| `polling` (automatic when the API address is `localhost`) | Local development | The worker asks Telegram for new messages every 3 seconds |
| `webhook` (automatic otherwise) | Deployed | Telegram calls `/webhooks/telegram/agentry` (team bot, set by the worker at start) and `/webhooks/telegram/<connection id>` (a business bot, set when it's connected). Each checks the `X-Telegram-Bot-Api-Secret-Token` header |

Set `AGENTRY_TELEGRAM_WEBHOOK_SECRET` to a long random string in production.

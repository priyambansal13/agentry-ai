# Connect Gmail (inbox triage)

About 15 minutes. You need a Google account to own the Google Cloud project. Google's console moves buttons around
now and then; if a label differs, look for the closest match.

## 1. Google Cloud project and Gmail API
1. Open https://console.cloud.google.com, then **Select a project → New project**, name it "Agentry", and create it.
2. **APIs & Services → Library**, search for **Gmail API**, and click **Enable**.

## 2. OAuth consent screen (Google Auth Platform)
1. **APIs & Services → OAuth consent screen** (or **Google Auth Platform → Branding**).
2. App name **Agentry**, a support email, and your developer contact email.
3. **Audience:** *External*, publishing status **Testing**. Under **Test users** add every Gmail address you'll connect
   while testing (up to 100).
4. **Data access → Add or remove scopes:** add `openid`, `.../auth/userinfo.email` and **`https://www.googleapis.com/auth/gmail.modify`**.

## 3. OAuth client
1. **Clients** (or **Credentials → Create credentials → OAuth client ID**). Type: **Web application**.
2. **Authorized redirect URIs:** `http://localhost:8801/connect/google/callback`
   (production: `https://<your-api-domain>/connect/google/callback`).
3. Copy the **Client ID** and **Client secret** into `.env`:
   ```
   AGENTRY_GOOGLE_CLIENT_ID=....apps.googleusercontent.com
   AGENTRY_GOOGLE_CLIENT_SECRET=....
   ```
4. Restart the API and worker.

## 4. Connect
1. Sign in to the portal (e.g. as `riya@sharmadigital.example`), then **Connections → Connect Gmail**.
2. Choose a Google account you added as a test user. In Testing mode Google shows *"Google hasn't verified this app"*:
   click **Continue** (this only appears for test users of your own app).
3. Tick the Gmail permission. You land back on Connections with "✓ Gmail connected".

## 5. Check it works
- From another address, email the connected inbox. Within about a minute:
  - it appears in **Conversations** with a category;
  - in Gmail it has an **Agentry/…** label;
  - if it needs a reply, a **draft** sits in the thread and the same draft is in **Needs you**.
- Approve it in **Needs you**: the reply is sent from your Gmail, in the same thread.
- **Check for new mail now** on the Connections page runs a sync immediately.

## 6. Optional: instant sync with Gmail push

Without this, Agentry checks Gmail every minute. With it, new mail is sorted within seconds.

1. Google Cloud → **Pub/Sub → Create topic**, e.g. `projects/<project>/topics/agentry-gmail`.
2. On the topic: **Permissions → Add principal** `gmail-api-push@system.gserviceaccount.com` with role **Pub/Sub Publisher**.
3. **Create subscription** on the topic: delivery type **Push**, endpoint
   `https://<your API domain>/webhooks/gmail?token=<a long random secret>`.
4. Add to `.env`:
   ```
   AGENTRY_GMAIL_PUBSUB_TOPIC=projects/<project>/topics/agentry-gmail
   AGENTRY_GMAIL_PUSH_TOKEN=<the same random secret>
   ```
5. Restart. Each connected inbox subscribes when it connects, and a daily job (05:00 IST) renews the subscription
   (Gmail's last 7 days). The once-a-minute check keeps running as a safety net.

## What Agentry can and can't do with this access
- Read new mail, add or remove labels, create and send drafts **you approved**. It never deletes anything.
- It starts from the moment you connect; older mail is not triaged.
- Disconnect at any time (Connections → Disconnect); Agentry also revokes its access at Google.

## Before real clients use it
- **Testing mode logins expire after 7 days**, so you'll need to reconnect. That's fine for demos, not for clients.
- **Publishing the app** for any Google user requires Google's **app verification**. Because `gmail.modify` is a
  *restricted* scope, it also requires an **annual third-party security assessment (CASA)**. Plan weeks and a fee.
- **Google Workspace clients** (business domains) can avoid that: their Workspace admin can trust the Agentry app for their
  organisation (or use domain-wide delegation). Ask Agentry to set this up per client.
- New mail is checked every minute. Instant push (Gmail → Cloud Pub/Sub → Agentry) can replace polling later.

# Setting up Outlook / Microsoft 365 for inbox triage

Agentry reads, categorises and drafts replies in a client's Outlook inbox through Microsoft Graph, the same way it
does for Gmail. You register **one app** for Agentry in Microsoft Entra; each client then signs in with their own
Microsoft account from Connections.

## 1. Register the app (once, for Agentry)

1. Go to **portal.azure.com → Microsoft Entra ID → App registrations → New registration**.
2. Name: **Agentry**. Supported account types: **Accounts in any organizational directory and personal Microsoft accounts** (multi-tenant).
3. Redirect URI: platform **Web**, `https://<your API domain>/connect/microsoft/callback`
   (in development: `http://localhost:8801/connect/microsoft/callback`).
4. **Certificates & secrets → New client secret**. Copy the value (shown once).
5. **API permissions → Add → Microsoft Graph → Delegated**: `offline_access`, `openid`, `email`, `User.Read`,
   `Mail.ReadWrite`, `Mail.Send`.

## 2. Add to `.env`

```
AGENTRY_MICROSOFT_CLIENT_ID=<Application (client) ID>
AGENTRY_MICROSOFT_CLIENT_SECRET=<the secret value>
AGENTRY_MICROSOFT_TENANT=common
```

Restart the API and worker. The client's Connections page now shows **Connect Outlook**.

## 3. Business accounts: admin approval

Many Microsoft 365 tenants don't let staff approve apps that read mail. The client then sees "Your Microsoft 365 admin
needs to approve Agentry first". Their admin opens this link once (replace the client ID) and approves:

```
https://login.microsoftonline.com/common/adminconsent?client_id=<AGENTRY_MICROSOFT_CLIENT_ID>
```

## What happens after connecting

- New mail in **Inbox** is sorted every minute (from the moment of connecting; older mail is left alone).
- Labels are **Outlook categories** (`Agentry/Client`, `Agentry/Urgent`…); promotions and spam can move to **Archive**.
- Reply drafts are created in the thread (**createReply**) and sent from the client's mailbox when approved.
- Replies the client sends from Outlook (**Sent Items**) are recorded, for response times and escalation.
- Several Outlook (and Gmail) inboxes can be connected per client.

Before production: Microsoft **publisher verification** removes the "unverified" warning on the sign-in screen.

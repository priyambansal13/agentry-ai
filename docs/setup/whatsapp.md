# Connect WhatsApp (WhatsApp Cloud API)

About 20–30 minutes for a test setup. Meta's dashboards change often; if a label differs, look for the closest match.

## 1. Meta developer app
1. Open https://developers.facebook.com, then **My Apps → Create app**, and choose the WhatsApp / "Connect with customers" use case
   (type *Business*). Link or create a Meta Business portfolio when asked.
2. In the app, open **WhatsApp → API Setup**. Meta gives you:
   - a **test phone number** (free; can message up to **5 verified recipients**),
   - its **Phone number ID** and **WhatsApp Business Account ID**,
   - a **temporary access token** (expires in about 24 hours).
3. Under **To**, add your own mobile number and verify it with the code Meta sends.
4. Note the **Graph API version** shown in the sample request (e.g. `v23.0`) and set it in `.env` if it differs:
   `AGENTRY_WHATSAPP_GRAPH_VERSION=v23.0`.

## 2. App secret and verify token
1. **App settings → Basic → App secret → Show**, and put it in `.env` as `AGENTRY_WHATSAPP_APP_SECRET=...`.
   Agentry uses it to verify that every webhook really comes from Meta.
2. `AGENTRY_WHATSAPP_VERIFY_TOKEN` is already generated in your `.env`. You'll paste it into Meta in step 4.
3. Restart the API and worker.

## 3. Public HTTPS address for webhooks (development)
Meta must reach your laptop over HTTPS. Easiest: a free Cloudflare quick tunnel:
```bash
brew install cloudflared
cloudflared tunnel --url http://localhost:8801
```
It prints an address like `https://random-words.trycloudflare.com` (it changes every time you restart it).

## 4. Subscribe the webhook
1. Meta app → **WhatsApp → Configuration → Webhook → Edit**.
2. **Callback URL:** `https://random-words.trycloudflare.com/webhooks/whatsapp`
   **Verify token:** the value of `AGENTRY_WHATSAPP_VERIFY_TOKEN`. Click **Verify and save**.
3. Under **Webhook fields**, **subscribe to `messages`**.

## 5. Connect the number in Agentry
1. Sign in as the client owner (e.g. `neha@smilecraft.example`) or as Agentry staff, then **Connections → WhatsApp**.
2. Enter the **Phone number ID**, **WhatsApp Business Account ID** and **access token**, then **Connect WhatsApp**.
   Agentry checks the credentials with Meta and stores the token encrypted.
3. **Send test** to your verified number. You'll receive Meta's "hello world" template.
4. Reply to it from your phone (e.g. "Do you have parking?"). The message appears in **Conversations → WhatsApp**:
   - In **approval mode** (default) the AI's answer waits in **Needs you**. Approve it and it's sent to your phone.
   - On **Automations → WhatsApp assistant → Switch to automatic**, the assistant replies instantly.

## Permanent token (temporary tokens expire daily)
Meta Business settings → **Users → System users** → add a system user → **Assign assets** (the app and the WhatsApp
account) → **Generate token** with `whatsapp_business_messaging` and `whatsapp_business_management`. Use that token in step 5.

## Rules Agentry follows
- Free-form replies only within **24 hours** of the customer's last message. Outside it, Meta requires an **approved
  template**, and Agentry marks such a reply "not delivered" instead of breaking Meta's rules.
- Voice notes, images and conversations a person has taken over go to the team (Needs you), not the AI.
- Every webhook is signature-checked; repeated deliveries of the same message are processed once.

## Before real clients use it
- **Business verification** of the Meta Business portfolio, a **real phone number** (not currently registered on the
  WhatsApp app) and an approved **display name**.
- **Templates** for messages Agentry starts (reminders, reactivation, alerts) must be approved by Meta.
- Meta charges per template message. Replies within the customer's 24-hour window are free.
- To connect many clients' numbers easily, become a Meta **Tech Provider** and use **Embedded Signup** (clients connect in a
  popup), or go through a WhatsApp partner (BSP).

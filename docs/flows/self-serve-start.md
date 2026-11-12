# Self-serve start: buy a plan on the website, open the account from the email

Plan: [PLAN-COMMERCIAL-2026-11.md](../PLAN-COMMERCIAL-2026-11.md) (#1). Code: `backend/src/agentry/signups.py`, API
`api/routes/signups_api.py`, the billing webhook (`api/webhooks.py`, `payment_link.paid` with `notes.signup_id`), worker
`worker/audit_jobs.py` (`signup.provisioned` → read the website), migration 0057; website `apps/web/src/app/start`,
`components/start.tsx`; portal `apps/dashboard/src/app/start/[id]` (route) and `start/[id]/finish`; HQ → Website sign-ups.
Tests: `tests/test_signups.py`.

```mermaid
flowchart TD
    V["Website /start (Pricing, 'Start now' on every try-it box, 'Switch it on' after /try)"] --> P["Plan + business, website, name, email, phone<br/>(human check, 3 a day per visitor)"]
    P --> G{"Razorpay configured?"}
    G -- no --> D["Demo request: a person calls to take payment"]
    G -- yes --> R["Razorpay payment link: setup + first month + GST"]
    R -- paid --> W["Webhook: sign-up paid · email the account link · tell ops"]
    W --> L["Link (proves the email) → portal makes the organisation + owner,<br/>claims the sign-up once, signs them in"]
    L --> F["Finish: plan's agents in setup, billing plan (setup billed, this month prepaid),<br/>'Plan' step done, website read into knowledge"]
    F --> O["Onboarding → go live in approval mode"]
```

| Plan (agent pack, `self_serve`) | Monthly | Setup | Agents on |
|---|---|---|---|
| Starter | ₹2,999 ($49) | none | Website chat, WhatsApp, speed-to-lead |
| Clinic growth | ₹6,999 ($99) | none | WhatsApp, website chat, appointment concierge, reviews, speed-to-lead (+ AI visibility, receptionist off) |
| CA Firm | ₹14,999 ($299) | ₹15,000 ($299) | the CA pack |

Prices are agent packs (HQ → Packs); `self_serve`, `sort` and `highlights` decide what the website shows. 18% GST for India.

- Nothing is created before payment. The account link goes only to the email that paid; the link's secret is stored hashed
  (to check) and encrypted (to email). A second click goes to the account (or sign-in).
- Only the owner who paid (same email, owner of the claimed organisation) can finish. A failed finish is shown in HQ.
- HQ → Website sign-ups: every sign-up, paid / opened / set up, with "Resend link" for paid ones not opened.
- Needs on the server: `AGENTRY_BILLING_RAZORPAY_KEY_ID`, `..._KEY_SECRET` and `..._WEBHOOK_SECRET` (Razorpay webhook for
  `payment_link.paid` → `/webhooks/billing/razorpay`). Without them the website still works and hands each sign-up to sales.

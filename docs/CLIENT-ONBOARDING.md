# Onboarding a client (Agentry HQ)

> **Rule:** the automations switched on for a client decide everything they see.
> - The menu, onboarding steps, connection cards, go-live checks, report rows and plan sections all follow them.
> - The API enforces the same rule: a hidden section returns 404, even by URL and even for Agentry staff.
> - Source of truth: `backend/src/agentry/features.py`.

## 1. Roles

| Who | Role | Can |
|---|---|---|
| Agentry staff | platform `admin` | Create clients, switch automations, set plans, invite people, open any client's portal (recorded in the audit log), issue statements |
| Client owner | `owner` | Everything in their business: connect accounts, settings, approve drafts, manage team, billing |
| Manager | `manager` | Day-to-day work and settings; no team management, no billing |
| Front desk | `staff` | Read conversations, approve/edit/reject drafts |
| Finance | `finance` | Billing and invoices only (no emails or chats) |
| Viewer | `viewer` | Dashboard numbers and reports only |

Permissions come from `config/roles.json`, the single source of truth for both the API and the dashboard.

### Inbox triage, per role (verified by `backend/tests/test_roles_inbox_triage.py` and a browser sweep)

| | Owner | Manager | Front desk | Finance | Viewer | Agentry staff |
|---|---|---|---|---|---|---|
| Needs you: see, edit, approve, discard drafts | ✓ | ✓ | ✓ | – | – | ✓ |
| Snooze, assign cards, use saved replies, correct a label | ✓ | ✓ | ✓ | – | – | ✓ |
| Manage saved replies, relearn writing style, inbox routing | ✓ | ✓ | – | – | – | ✓ |
| Conversations, Leads, Knowledge (read) | ✓ | ✓ | ✓ | – | – | ✓ |
| Knowledge, persona, triage settings, pause | ✓ | ✓ | – | – | – | ✓ (also Agentry-managed fields) |
| Connections (connect / disconnect Gmail) | ✓ | ✓ | – | – | – | ✓ |
| Get live (onboarding) | ✓ | ✓ | – | – | – | ✓ |
| Business profile | ✓ | – | – | – | – | ✓ |
| Audit log | ✓ | ✓ | – | – | – | ✓ |
| Billing | ✓ | – | – | ✓ | – | ✓ |
| Export data (CSV) | ✓ | – | – | – | – | ✓ |
| Team: invite, change role, remove, cancel invite | ✓ | – (view) | – (view) | – (view) | – (view) | ✓ |
| Urgent-email alerts | on | on | opt-in | – | – | – |
| Second alert when an urgent email is still unanswered (escalation) | on | opt-in | opt-in | – | – | – |
| Daily digest | on | on | opt-in | – | – | – |
| Monday summary (email or WhatsApp) | on | opt-in | opt-in | opt-in | opt-in | – |
| Statement emails | on | – | – | on | – | – |

- **Who sent each reply:** every sent reply records who approved it, and the conversation shows that person's name. The audit log records every approval, edit, setting change and team change.
- **Gaps in a draft:** when the AI lacks a fact (e.g. a price), it leaves a `[gap]`, and sending stays blocked until a person fills it in.
- **If the AI can't write a draft:** the card says so (models unavailable), and ops are alerted.

### Website chat agent, per role (verified by `backend/tests/test_roles_website_chat.py` and a browser run with a real visitor)

| | Owner | Manager | Front desk | Finance | Viewer | Agentry staff |
|---|---|---|---|---|---|---|
| See chats and hand-off requests | ✓ | ✓ | ✓ | – | – | ✓ |
| Reply to a visitor, take over, hand back to the agent | ✓ | ✓ | ✓ | – | – | ✓ |
| Test the agent, edit knowledge, persona, settings | ✓ | ✓ | – | – | – | ✓ |
| Install snippet (Get live → Connect accounts) | ✓ | ✓ | – | – | – | ✓ |
| "A visitor needs a person" alert | on | on | opt-in | – | – | – |

**The hand-off loop:**
1. The visitor asks for a person, and the agent hands the chat off.
2. Alerts go out, and a **Reply now** card appears in Needs you.
3. A person replies from the conversation page.
4. The visitor sees the reply in the widget within about 4 seconds, with no reload. While a person is handling the chat, the agent stays silent.
5. **Hand back to the agent** returns the chat to the AI.

Replies in WhatsApp and Gmail conversations go out from the business's own number or mailbox.

### WhatsApp assistant, per role (`backend/tests/test_roles_whatsapp.py`, against a simulated Meta API)

| | Owner | Manager | Front desk | Finance | Viewer | Agentry staff |
|---|---|---|---|---|---|---|
| Connect WhatsApp, send a test message | ✓ | ✓ | – | – | – | ✓ |
| See and approve AI replies, reply from the portal | ✓ | ✓ | ✓ | – | – | ✓ |
| Take over / hand back to the assistant | ✓ | ✓ | ✓ | – | – | ✓ |

Voice notes, images and "I want a person" go to the team, and the assistant stays quiet until someone hands the chat back. Replies are sent from the business's own number, and only within Meta's 24-hour window.

### Invoice follow-up, per role (`backend/tests/test_roles_invoices.py`)

Invoice items are money matters, so they follow the **invoice** permission, not the conversation permission:

| | Owner | Manager | Front desk | Finance | Viewer | Agentry staff |
|---|---|---|---|---|---|---|
| Invoices: see | ✓ | ✓ | – | ✓ | ✓ | ✓ |
| Import, record payment, pause reminders | ✓ | ✓ | – | ✓ | – | ✓ |
| Reminder drafts, disputes, payment checks in Needs you | ✓ | ✓ | – | ✓ | see | ✓ |
| Invoice conversations: see / reply | ✓ | ✓ | – | ✓ | see | ✓ |
| Connect Razorpay / Stripe | ✓ | ✓ | – | – | – | ✓ |
| Resolve a dispute (reopen, write off, void); confirm "customer says paid"; match an unmatched payment | ✓ | ✓ | – | ✓ | – | ✓ |

### Lead reactivation and speed-to-lead, per role (`backend/tests/test_roles_lead_engine.py`)

| | Owner | Manager | Front desk | Finance | Viewer | Agentry staff |
|---|---|---|---|---|---|---|
| Leads list | ✓ | ✓ | ✓ | – | – | ✓ |
| Campaigns: see | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| Import old leads, start a campaign | ✓ | ✓ | – | – | – | ✓ |
| Lead forms (Leads page; speed-to-lead only) | ✓ | ✓ | – | – | – | ✓ |
| Approve outreach drafts in Needs you | ✓ | ✓ | ✓ | – | – | ✓ |

### AI receptionist (voice), per role (`backend/tests/test_roles_voice.py`, `test_voice.py` and browser calls)

| | Owner | Manager | Front desk | Finance | Viewer | Agentry staff |
|---|---|---|---|---|---|---|
| Talk to your agent (browser test call) | ✓ | ✓ | – | – | – | ✓ |
| Receptionist settings (when it answers, transfer number) | ✓ | ✓ | – | – | – | ✓ |
| Calls in Conversations: transcript, summary, recording | ✓ | ✓ | ✓ | – | – | ✓ |
| "Call back" cards in Needs you (caller asked for a person or needs a follow-up) | ✓ | ✓ | ✓ | – | – | ✓ |
| Delete a recording; set how long recordings are kept | ✓ | ✓ | – | – | – | ✓ |

## 2. The workflow

| # | Step | Where | Who |
|---|---|---|---|
| 1 | Price the deal | HQ → Proposal builder | Staff |
| 2 | **Create the client:** business details, **automations they bought**, owner's name and email, pricing plan (suggested from the automations, editable) | HQ → **+ New client** | Staff |
| 3 | The owner gets an invitation email → **one click** signs them in and joins the business → they set a password (or skip and use emailed sign-in links) | Email → portal | Owner |
| 4 | Onboarding: only the steps their automations need | HQ → client → **Do their onboarding** (staff), or the owner's **Get live** | Staff or owner |
| 5 | Connect accounts: Gmail and/or WhatsApp, Razorpay/Stripe. Only the cards their automations use are shown | Connections | **Owner** (their Google/Meta login) |
| 6 | Go live: requires the checks for their automations. Automations switch from *setup* to **approval mode** | Get live → Go live | Staff or owner |
| 7 | The owner invites their team | Team | Owner (or staff from the HQ client page) |
| 8 | Upsell later: switch on another automation; a live client gets it in approval mode | HQ → client → Automations | Staff |
| 9 | Monthly: draft statement on the 1st → staff issue it → email + payment link → 7-day dispute window | HQ → client → Statements | Staff → owner/finance |

## 3. What each automation brings

| Automation | Portal sections | Connections | Onboarding steps | Go-live checks |
|---|---|---|---|---|
| Inbox triage | Needs you, Conversations, Leads, Knowledge | Gmail | connect, knowledge, settings, persona | Gmail connected |
| Website chat | Needs you, Conversations, Leads, Knowledge, Calendar | — (widget snippet) | connect, knowledge, persona, test | knowledge, test chat |
| WhatsApp assistant | Needs you, Conversations, Leads, Knowledge, Calendar | WhatsApp | connect, knowledge, persona, compliance | WhatsApp connected |
| Invoice follow-up | Needs you, Conversations, Invoices | Gmail, WhatsApp, Razorpay/Stripe | connect, import, settings, compliance | invoices imported, Gmail or WhatsApp |
| Lead reactivation | Needs you, Conversations, Leads, Campaigns, Calendar | WhatsApp, Gmail | connect, import, settings, persona, compliance | Gmail or WhatsApp |
| Speed-to-lead | Needs you, Conversations, Leads, Calendar | WhatsApp, Gmail | connect, settings, persona, compliance | Gmail or WhatsApp |
| AI receptionist | Needs you, Conversations, Leads, Knowledge, Calendar | — (phone number from 4.3) | knowledge, settings, persona, test | knowledge, test, **phone number connected** (can't pass until milestone 4.3) |

**Always shown:**
- Sections: Home, Automations, Reports, Team, Audit log, Billing, Notifications & data.
- Onboarding steps: profile, plan, team, go live.
- Go-live check: business profile.

The AI receptionist can be switched on and set up now: the client tests it in the browser. It can't go live until phone numbers arrive (PHASE-4-VOICE.md 4.3). Cold email and content repurposing appear in HQ as *coming soon* and can't be switched on yet.

## 4. Example: inbox triage only

- **The client sees:** Home, Needs you, Automations, Conversations, Leads, Knowledge, Reports, Team, Audit log, Billing, Connections (Gmail only), Notifications & data.
- **Onboarding steps:** profile → plan → team → connect → knowledge → settings → persona → go live.
- **Go live needs:** the business profile and a connected Gmail.
- **Suggested plan:** ₹5,000 setup + ₹4,999/month + 18% GST, with optional included-email limits and overage.
- **Reports** lead with time saved (emails sorted × ~2 min), not ROI, since there are no bookings or recoveries to value.

## Invitations (how joining works)

- **New person** (has never signed in): the email link `/invite/<id>` signs them in on the spot. It makes a one-time sign-in link and uses it immediately, without sending a second email. They join with the invited role and are offered **Set a password** (skippable). The link stops signing anyone in once used, cancelled, or after 7 days.
- **Someone who already has an Agentry login:** added straight away, with a "you now have access" email. If an invitation for them does exist, its link takes them to the normal sign-in first.
- **Mail scanners** that open links in emails can't use an invitation up: each click makes a fresh one-time sign-in.


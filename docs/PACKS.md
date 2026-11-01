# Packs: sellable bundles of agents (first: CA Firm)

A **pack** is a bundle Agentry sells to one kind of business: a name, the agents in it (each on or off by default) and a
suggested price per currency. Every agent stays a **standalone** agent too:

| How a client gets an agent | Example | What happens |
|---|---|---|
| **Pack** | "CA Firm pack" | HQ assigns the pack; the agents ticked for this client are switched on and marked *in pack* |
| **Pack, tailored** | CA Firm without the voice receptionist | HQ unticks agents for this client only; the pack itself is unchanged |
| **Standalone (add-on)** | Content repurposing on top of the CA pack, or Bookkeeping alone | HQ switches it on as before; marked *add-on* |

- Any agent can be put in any pack (HQ → Packs → edit). A pack can contain agents that are **coming soon**: they're
  listed for clients who bought the pack and are switched on when they're built.
- Changing a client's pack switches off the agents of the old pack that aren't in the new one; add-ons are never touched.
- Removing a pack keeps its agents as add-ons (or switches them off, if HQ chooses).
- A pack's price is a starting point: assigning a pack can fill the client's pricing plan (setup fee, monthly retainer,
  included usage), and every number stays editable per client.
- Industry packs (`backend/packs/*.yaml`: persona, FAQs, services for demos) are a different thing and stay as they are.

Data: `app.agent_packs` (platform table, edited in HQ), `org_settings.agent_pack` + `agent_pack_agents` (what this
client bought, including coming-soon agents), `automation_instances.source` (`pack` or `standalone`). Migration 0034.

## The CA Firm pack

For chartered accountants, tax consultants and small law/compliance firms. Built from the CA ideas and from what the
cloned projects do well (filing board from *jira-clone*, recurring entries and budget alerts from *ai-finance-platform*,
vision extraction with confidence from *ai-recipe-platform*).

### On by default

| Agent | Status | What it does for the firm |
|---|---|---|
| Inbox triage | built | Client emails sorted, replies drafted, notices and deadlines flagged |
| WhatsApp assistant | built | Clients ask questions and send documents on WhatsApp |
| **Document chaser** | new | A checklist per client per filing (built from last year's return); polite WhatsApp/email reminders until every document is in; files named and filed |
| **Tax documents reader** | new | Form 16, AIS, TIS, 26AS read into one standard sheet per client; **mismatch finder**: what's in AIS but not declared, TDS not matching |
| **Filing tracker** | new | A board per period (ITR AY 2026-27, GST Oct 2026): Docs pending → In prep → Review → Filed → Verified, owner and due date per card, "my work" view; clients ask "is my ITR filed?" on WhatsApp and get the answer |
| **Compliance calendar** | new | GST, TDS, advance tax, ROC (AOC-4, MGT-7, DIR-3 KYC), PF/ESI dates per client; reminders to the client and to the staff member responsible |
| Invoice follow-up | built | The firm's own fees collected without awkward calls |
| Bookkeeping | built | Bills by photo → checked → Tally |

### Optional (off by default, tick per client)

| Agent | Status | What it does |
|---|---|---|
| **ITR preparation** | new | Tax computation in the firm's template, old vs new regime, ITR JSON in the department's schema for the CA to upload |
| **Capital gains** | new | Broker P&L (Zerodha, Groww, Upstox), CAMS/KFintech statements → STCG/LTCG with grandfathering → Schedule CG |
| **Bank statement classifier** | new | Statement lines tagged income / expense / drawings / transfer, learning from corrections → trial balance, 44AD/44ADA working |
| **Notice handler** | new | 143(1), 139(9), 148 notices explained in plain words, difference computed, reply drafted, deadline tracked |
| **GST reconciliation** | new | GSTR-2B vs purchase register: missing invoices, wrong GSTIN, amount differences; messages to suppliers who haven't filed |
| **TDS returns** | new | 24Q/26Q data, PAN checks, late deduction interest, Form 16/16A to employees and vendors |
| **Tax audit (3CD)** | new | 40A(3), 43B, 43B(h) MSME and other clauses from the books, exceptions flagged for the auditor |
| **Recurring entries & budgets** | new | Rent, retainers, EMIs booked on their dates; an alert at 80% of a budget, once a month |
| **Excel desk** | new | Any PDF → Excel in the firm's layout, reconciliations (books vs bank, debtors), "ask your spreadsheet" |
| Appointment concierge | built | Client meetings booked and reminded |
| AI receptionist | built | Calls answered in tax season |
| Website chat | built | Enquiries from the firm's website |

### Price (suggested, editable per client)

INR: setup ₹15,000, ₹14,999/month, 3,000 messages and 1,500 emails included. USD: setup $299, $299/month.
Per-return and per-GSTIN pricing needs new usage metrics (`returns_filed`, `gstins`); they come with the filing tracker.

### Ground rules for every CA agent

- **The CA files.** The tax portal has no open filing API (only registered ERIs). Agents prepare; the CA reviews and uploads.
- **No portal passwords stored.** The client or CA downloads AIS/26AS and uploads it.
- **Every number traceable** to the source line, like the content agent's quote checks. A number that can't be traced
  is flagged, never guessed.
- **DPDP Act:** PAN, Aadhaar and bank data stay in the client's tenant (RLS), encrypted files, audit log, deletion on request.

## Build order

1. ✅ **Packs** (this change): pack catalog in HQ, assign / tailor / remove per client, add-ons, CA Firm pack seeded with
   the new agents as *coming soon*.
2. **Filing tracker + status on WhatsApp**: the board the other CA agents move cards on; `returns_filed` metric.
3. **Document chaser**: checklists, reminders, documents filed against the card.
4. **Tax documents reader + mismatch finder** (Document AI with confidence, every number traced).
5. **Compliance calendar**, then **GST reconciliation** (monthly revenue all year).
6. ITR preparation, capital gains, bank classifier, notice handler, TDS, 3CD, recurring entries, Excel desk.

Cross-cutting ideas from the cloned projects, for all agents: a prompt-injection guard on everything strangers type
(chat, WhatsApp, inbox, reviews); live progress steps instead of spinners; read-only share links and PDF export of
reports; usage shown as "8 of 10 used" with locked features shown, not hidden.

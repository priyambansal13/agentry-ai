# Mock pilot clients

Fake data for building and testing before real pilots. All names, emails (`.example` domain), phone numbers and GSTINs are fictional.

Dates are anchored to **2026-10-24** (`tenants.json → anchorDate`). The seed script shifts every date by `today − anchorDate`, so the "days overdue" mix stays the same whenever you run it.

**More test invoices:** [`invoices/`](invoices/README.md): an INR sheet, a USD QuickBooks report and an Excel ledger,
one row per behaviour, plus sample customer replies.

## Tenants

| Tenant | Market | Invoice source | Email | Channels | Gateway | Pricing model | Sequence |
|---|---|---|---|---|---|---|---|
| **Sharma Digital Agency** (Delhi) | India, INR | Google Sheets → `sharma-digital-sheet.csv` | Gmail | Email + WhatsApp | Razorpay | Hybrid: ₹4,999 + 1.5% overdue-only, capped | Default 7/14/21/28, approval on all steps |
| **Kaveri Industrial Supplies** (Coimbatore) | India, INR, GST B2B | Tally → `kaveri-tally-bills-receivable.csv` + `kaveri-tally-parties.csv` | Outlook | Email + WhatsApp | Razorpay | Commission only: 4%, strong attribution only | Custom 0/15/30/45/60 (45-day credit) |
| **Brightpath Consulting** (Austin) | US, USD | QuickBooks → `brightpath-qbo-open-invoices.csv` | Gmail | Email only | Stripe | Subscription: $199, no commission | Default, auto-send |

Together the three tenants exercise all three pricing models, four source formats (sheet, Tally report + ledger master, QBO report), both gateways, both mail providers, and three timezones.

## Scenario coverage

| Scenario | Where |
|---|---|
| Each reminder step (7, 14, 21, 28) is due today | SDA-2041 (7), SDA-2042 (14), SDA-2052 (21), SDA-2044 (28) |
| Missed run catch-up (day 9, step 7 never sent) | SDA-2047 |
| Past final step → human hand-off | SDA-2045 (34 days) |
| Not yet due / pre-due heads-up | SDA-2046, SDA-2050, BP-1111 (due today) |
| Already paid → ignore | SDA-2048, Kaveri 0561 |
| Partial payment, remind for the balance | SDA-2043, Kaveri 0455, BP-1109 |
| Same customer, several open invoices | Northstar (SDA-2041, 2049), Chai Point (2042, 2051), Annapoorna, Deccan, Harbor |
| Missing phone → email only | Coromandel Foundry |
| Large B2B amounts, Indian number format (1,12,400) | Kaveri |
| Custom cadence | Kaveri `sequenceOverride` |

## Replies (`replies.jsonl`): classifier test set

20 labelled replies in English, Hindi, Hinglish and Tamil covering `promise_to_pay`, `already_paid` (UTR, NEFT ref, cheque, screenshot), `dispute`, `resend_invoice`, `partial_payment`, `ooo`, `wrong_contact`, `opt_out` and `other`. Each row has the `expected` output, so it can be used directly as the CI evaluation set (target ≥ 90%).

## Payment events (`payment-events.jsonl`)

Webhook-style events with expected outcomes: strong match through link metadata, partial payment, an ambiguous match (customer owes two invoices) sent to a human, a failed payment that is ignored, a weak Tally-sync match on a strong-only plan (no commission), a Stripe match, and a **replayed duplicate** to test idempotency.

To use in Google Sheets: import `sharma-digital-sheet.csv` into a new sheet to test the Sheets connector end to end.

## The Boring Machine: `boring-machine/`

**SmileCraft Dental Clinic** (Pune, INR, English/Hindi/Marathi): a B2C appointment business, which is the best fit for "calendar full of booked appointments".

| File | What |
|---|---|
| `tenant.json` | Services, staff calendars, hours, holidays, persona "Asha", qualification questions, FAQs, enabled sources (cold email **off**), ownership priority, pricing (base + per booking, higher price for high-value services) |
| `old-leads.csv` | Reactivation list: quoted, no-show, due for a check-up, opted out, no consent, and a **duplicate** with a different phone format and email |
| `form-leads.jsonl` | Incoming form and Meta ads leads: urgent pain, after-hours lead, duplicate of an old lead (ownership hand-over), spam, out-of-area |
| `scenarios.jsonl` | Scripted chat, call (including Hindi), WhatsApp reactivation, reminder, no-show and reschedule scenarios with expected results |

## Inbox triage: `inbox-triage/`

`sharma-inbox.jsonl`: one day of Sharma Digital Agency's inbox (16 emails) with expected category (Urgent / Client / Promotion / Spam / Lead / Invoice-Payment / Newsletter / Other), urgency + alert channel, needs-reply, extracted fields and events emitted. Covers urgent client issues, a legal notice, new leads with budget, invoice replies (promise and dispute) that chain into the invoice automation, a Razorpay receipt, phishing, and an after-quiet-hours email. It also feeds the **opportunity report** test.

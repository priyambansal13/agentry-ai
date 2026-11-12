# MSME 45-day recovery (part of invoice follow-up)

Plan: [PLAN-COMMERCIAL-2026-11.md](../../PLAN-COMMERCIAL-2026-11.md) (#4). Code: `backend/src/agentry/automations/invoice_follow_up/msme.py`,
API `api/routes/msme_api.py` (`/org/invoices/msme`), reminders (`sequences.compose`), daily cards (`worker/due_date_jobs.py`
`msme-daily`, 09:45 IST), official figures `msme.bank_rate` / `msme.max_days` / `msme.default_days` (`official_rules.py`),
migration 0060; portal Invoices → MSME 45-day rule (+ `/api/msme-claim/{contact}`); website invoice follow-up page calculator
(`/public/playground/msme`). Tests: `tests/test_msme.py`.

| Rule (MSMED Act, 2006) | How it's applied |
|---|---|
| s.15: pay by the date agreed in writing, at most 45 days; 15 days without an agreement | Legal due date = invoice date + the customer's written credit days (capped at 45) or 15. Set per customer on the Invoices page. |
| s.16: compound interest with monthly rests at 3× the RBI bank rate | From the legal due date until paid: whole 30-day months compound, a part month pro rata. Bank rate 5.75% (Nov 2026) → 17.25% a year, an official figure checked daily. |
| Only micro and small **manufacturers and service providers** | Medium enterprises and traders can't switch it on (traders may hold Udyam but aren't "suppliers" under the Act); a Udyam number is required. |
| Buyer's income tax: a late payment to a micro / small enterprise is deductible only in the year it's actually paid | To a business buyer (the firm's tick, else a company name or GSTIN) the reminder adds one sentence citing section 43B(h) of the Income-tax Act, 1961 for invoices up to FY 2025-26, and section 37(2)(g) of the Income-tax Act, 2025 from 1 April 2026 (confirmed on [incometaxindia.gov.in](https://wm.incometaxindia.gov.in/w/section-37-176)). Both references are official figures, so the daily check watches them. |

- **Reminders:** polite, firm and final reminders on an invoice past its legal due date end with a short, factual paragraph
  (registration, legal due date, rate, interest so far), added by code from the database. The writer's "no legal threats"
  rule is unchanged.
- **Needs you:** one card per invoice the day it crosses the legal due date (never again, even after it's dealt with).
- **MSME Samadhaan draft** per customer (Markdown): supplier and Udyam, buyer, credit terms, every late invoice with its
  legal due date, days late and interest, totals, what to attach. Checked by a person and filed at samadhaan.msme.gov.in.

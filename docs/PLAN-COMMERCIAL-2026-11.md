# Plan: four things that make money (2026-11-12)

Why these four: the website now brings people in (free audit, instant demo, a try-it box on every agent page), but every one
of them still has to wait for a demo call before paying. These turn that interest into revenue, add two agents that are easy
to sell, and open the biggest deal size we have (CA firms reselling to their own clients). Prices below are suggestions to
confirm, not tested.

| # | What | Who pays | Suggested price | Builds on |
|---|---|---|---|---|
| 1 | **Self-serve start**: pick a plan, pay the first month, account ready, assistant in approval mode | Small businesses from the website | Starter ₹2,999 / Clinic ₹6,999 / CA firm ₹14,999 a month | `clients.provision`, agent packs, Razorpay payment links, instant demo |
| 2 | **Missed-call recovery**: every missed call gets a WhatsApp within a minute; the assistant takes it from there | Clinics, home services, shops | ₹1,499 a month add-on (or per recovered booking) | WhatsApp, `reach_contact`, contacts, bookings, billing outcomes |
| 3 | **CA client portal (white-label)**: the firm's clients see their filings, what's missing and due dates, and upload documents, under the firm's name | CA firms | ₹99 per active client a month | CA pack (clients, filings, chaser, calendar), the job-application upload page pattern |
| 4 | **MSME 45-day recovery**: legal due date, interest at 3× the RBI bank rate, a stronger reminder, and a MSME Samadhaan claim draft | Manufacturers, traders, suppliers | ₹2,999 a month or a % of money recovered | Invoice follow-up, official figures (RBI bank rate), approvals |

## 1. Self-serve start
- Website `/start` (and "Switch it on" from `/try`, `/audit` and every agent page): pick a plan, business name, website, your
  name, email, phone; human check.
- Plans are agent packs marked self-serve, each with a price: Starter (website chat + WhatsApp + speed-to-lead), Clinic
  growth (WhatsApp, website chat, appointment concierge, reviews, missed-call recovery, AI visibility), CA firm (the pack).
- Payment: a Razorpay payment link for the first month (+ setup if any). Paid → the account is made automatically: the
  organisation, the owner's invite (email with a sign-in link), the plan's agents in setup, billing plan saved, HQ alerted,
  the website and instant-demo pages read into the knowledge base. Monthly statements then bill as today.
- Without Razorpay keys (or if the visitor picks "talk to us first") it becomes a demo request as today.
- Abuse: Turnstile, one pending sign-up per email, payment before any account.

## 2. Missed-call recovery (new agent `missed_call_recovery`)
- A webhook per business (`/hooks/calls/{key}`) that their phone provider (Exotel, MyOperator, Knowlarity, TATA Tele, or
  any IVR that can call a URL) calls on every missed / unanswered / busy call. Generic fields mapped: from, to, status, time.
- Within a minute: a WhatsApp to the caller (approved template, the business's name, "how can we help?"), once per caller per
  day, not to staff numbers or opted-out contacts, quiet hours respected (sent at opening time instead).
- Replies go to the WhatsApp assistant, which answers and books.
- Results: missed calls, messaged, replied, booked; a booking within 7 days of the missed call counts as recovered (billable
  per recovered booking if the plan says so). Daily count in Business Pulse.

## 3. CA client portal
- The firm turns it on and sets its name, logo and colour (org brand). Each client gets a private link (no password), sent
  on WhatsApp or email from the client's page; it lasts 90 days and can be revoked.
- The client sees: their filings and status, what's still needed for each, upcoming due dates (with sources and
  extensions), and uploads photos / PDFs, which go through the document chaser (matched to the checklist item, filed).
- Shown under the firm's name and colours ("Sharma & Associates client portal"); Agentry appears only as "powered by".
- Billing: active portal clients a month (opened the link or uploaded) as a usage line.

## 4. MSME 45-day recovery (in Invoice follow-up)
- The business's Udyam number and category; each customer's agreed credit days (none written = 15 days; at most 45).
- Each invoice: the legal due date (MSMED Act section 15), and once past it, interest at three times the RBI bank rate,
  compounded monthly (section 16), shown on the invoice and the cash view. The bank rate is an official figure (source RBI,
  checked daily).
- Reminders past the legal date mention the right under the MSMED Act (polite, firm, then final), and that the buyer can't
  deduct the expense until it's paid (43B(h)) when the buyer is a business.
- A MSME Samadhaan claim draft per customer (invoices, dates, interest worked out) to file at samadhaan.msme.gov.in; a card in
  Needs you when an invoice crosses 45 days.

## Order
1, 2, 3, 4, each tested, documented and committed on its own. Deploy when asked.

# Test invoices

Three files to import on **Invoices → Import** (any client with invoice follow-up). All names, emails (`.example`)
and phone numbers are fictional; Agentry never emails `.example` addresses through a real mail server.
Dates are fixed around **25 Oct 2026**: "due today" rows are only exactly due on that day. After that the reminder
schedule catches up (it sends only the latest step that is due), so the files stay useful; edit the dates to test a
specific step on another day.

| File | Format | Rows | Import into |
|---|---|---|---|
| `india-sheet.csv` | Google Sheets export, INR, with a **WhatsApp consent** column | 15 | an INR client |
| `us-quickbooks.csv` | QuickBooks "Open invoices" report, USD | 6 | a **USD** client (no currency column: the client's currency is used) |
| `excel-ledger.xlsx` | Excel with different column names (Invoice No, Balance Due, Payment Due, WhatsApp opt-in…) | 6 | an INR client |

## What each India row tests

| Invoice | Situation | What should happen |
|---|---|---|
| MSR-1001 | 7 days overdue | First (friendly) reminder |
| MSR-1002 | 14 days overdue | Second reminder, email + WhatsApp (consent: yes) |
| MSR-1003 | 21 days overdue, WhatsApp consent: no | Third reminder by email only; WhatsApp skipped ("no consent") |
| MSR-1004 | 28 days overdue | Final reminder; once sent, a "time for a call" card |
| MSR-1005 | 40 days overdue | Catch-up: only the latest (final) reminder, then the call card |
| MSR-1006 | Part paid (₹20,000 of ₹47,300) | Reminders ask for ₹27,300; the payment link is for ₹27,300 |
| MSR-1007 | Due in 5 days | Nothing yet |
| MSR-1008 | Due today | Nothing until day 7 |
| MSR-1009 | No email or phone | "No email or phone: no reminders" badge; import reports 1 without contact |
| MSR-1010 | Already paid | Ignored |
| MSR-1011 | Same customer as MSR-1001 | One contact with two invoices |
| MSR-1012–1015 | Overdue | Use with the sample replies below |

US file: BRK-301/302 reminders, BRK-303 part paid ($460 open), BRK-304 not due, BRK-305 past final step, BRK-306 paid.
Excel file: INV/26/7002 part paid (₹89,000 open), INV/26/7004 not due, INV/26/7005 final reminder, INV/26/7006 no email
(WhatsApp only, if consent and WhatsApp are set up).

## Sample customer replies

Reply in the reminder's thread (or on WhatsApp) with one of these, then check Needs you and the invoice's notes:

| Reply | Use on | Expected |
|---|---|---|
| "Sorry for the delay, we will clear it by 5 November." | MSR-1001 | Promise to pay: reminders paused until the day after |
| "The amount is wrong: we agreed ₹60,000, not ₹72,000. Please send a corrected invoice." | MSR-1012 | Dispute card; reminders stop; resolve with **Dispute resolved: reopen** / **Write off** / **Void** |
| "We paid this on 20 Oct, UTR 412233558899." | MSR-1013 | "Customer says paid" card → **Confirm paid** closes it |
| "Bhai payment next week kar denge, abhi thoda tight hai." | MSR-1014 | Promise to pay (Hinglish) |
| "Can you resend a copy of the invoice? Our accounts team can't find it." | MSR-1002 | Card for a person |
| "We'll pay half now and the rest next month." | MSR-1004 | Part payment: card + reminders paused 7 days |
| "I'm out of office until 3 November." | MSR-1003 | Reminders paused 5 days |
| "Please don't stop the service, payment is on the way." | MSR-1005 | NOT an opt-out |
| "STOP" | MSR-1011 | Opted out of that channel; no more reminders there |
| "Can we pay in two parts?" | MSR-1015 | Card for a person |

**Payments to try:** record ₹88,800 for MSR-1015 (or send a Razorpay test webhook for ₹88,800 from that customer) →
matched, invoice paid, any waiting reminder withdrawn. A payment for MSR-1010 (already paid) → a "check a payment" card.

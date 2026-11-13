# Anomaly finder (CA desk part 2, #2)

A ledger, day book or sales / purchase register checked the way a reviewer would, before the partner or the auditor sees it.
Fixed rules, no AI: every finding lists its rows and why it matters, most serious first.

## Where
- Portal, on a **client's page** (Tools → Anomaly finder): the client's own GSTIN decides same-state vs other-state, and the
  file is kept on the client. Also on the **Excel desk → Find anomalies** for the firm's own sheets (state worked out from the
  rows). Both have "Try the sample". **Download Excel**: Findings, Rows, Benford, Not checked.
- Website: `/agents/ca-anomaly-finder` runs the same engine on a 167-entry sample purchase day book, or up to 60 pasted rows.
- Switched on with the Excel desk (`excel_desk`); viewers can look but not run it.

## The checks
The sheet is first read by the Excel cleaner (header, totals, page breaks, amounts, dates), keeping duplicate rows.

| Severity | Check | Rule |
|---|---|---|
| high | Same row twice | every column identical |
| high | Same party, amount and day | different voucher numbers |
| high | Voucher / invoice number used twice | |
| high | Cash paid above the 40A(3) limit | per person per day, split entries added up (official figure `audit.cash_limit`) |
| high | Cash received at or above the 269ST limit | rows marked receipt / sales (official figure `audit.cash_receipt`) |
| high | Wrong tax type | IGST on a same-state supply, CGST + SGST on an other-state one (place of supply column, else the party's GSTIN) |
| high | GSTIN not valid | format, state code, check digit |
| high | Outside the year / future | the year most dates fall in (or the one given) |
| medium | Just under a limit | within 3% under ₹10,000 (cash only), the 194C single-bill limit, ₹50,000, ₹2 lakh |
| medium | Tax not at a GST rate | total GST % of taxable value not 5 / 12 / 18 / 28 / 40 (or the special rates) |
| medium | Far above the party's usual | the party's largest entry over 4× the next largest (5+ entries, ₹25,000+) |
| medium | National holiday | 26 Jan, 15 Aug, 2 Oct |
| low | Sunday entries, round amounts (when they stand out), gaps in a voucher series | |
| low / medium | Benford first-digit test | chi-square, 8 degrees of freedom: fits under 15.5, doesn't fit over 20.1 (1%); needs 100+ amounts |

A check whose columns aren't in the sheet is skipped and listed under "Not checked".

## How it helps
Hours of filters and sorting per ledger become seconds, every ledger is checked the same way whoever reviews it, and the
problems that cost money (disallowed cash, tax paid the wrong way, ITC on a bad GSTIN, a bill booked twice) are fixed with
the client before the return or the audit.

## Code
`backend/src/agentry/automations/ca/anomalies.py` (`find`, `compute`, `sheet`); routes `/org/ca/excel/anomalies(/sample)` and
`/org/ca/clients/{cid}/anomalies(/sample)` (agent `ca_anomaly_finder` in `app.ca_work`); website kind `anomalies`; tests
`backend/tests/test_ca_anomalies.py`. Sample: `backend/samples/ca/purchase_daybook_sample.csv` (every planted problem is in the
test).

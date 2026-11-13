# Plan: CA desk, part 2: the daily spreadsheet work (2026-11-12)

What a CA firm's staff do every day that the 13 CA agents don't yet: clean the messy Excel clients send, look for what's wrong
in a ledger before the partner does, take a pile of files from a client and put each where it belongs, prepare GSTR-1, turn a
trial balance into financial statements, work out depreciation, and chase balance confirmations. Each is built the same way as
the existing CA tools: upload on the client's page (or a sample), the result saved on the client's work list with an Excel
download, a try-it box on the website, tests, a flow doc. Calculations are done by code (exact and explainable); the AI is used
only where judgement is needed and is always checked.

| # | Agent | What it does | AI? |
|---|---|---|---|
| 1 | **Excel cleaner** | A messy sheet in, a clean one out: the real header row found, blank / total / repeated-header rows removed, numbers stored as text ("1,23,456.00 Dr", "(1,200)", "₹5,000") made numbers, Dr / Cr in one signed column, every date in one format (ambiguous ones flagged), PAN / GSTIN checked (check digit) and upper-cased, phone numbers tidied, exact duplicates removed, near-duplicate party names grouped. A change log of everything done. | No |
| 2 | **Anomaly finder** | A ledger / day book / sales or purchase register scanned for what a reviewer looks for: duplicates, round sums, amounts just under limits (₹10,000 cash, ₹50,000, ₹2 lakh), Sunday and holiday entries, outliers for a party or ledger, invoice-number gaps and repeats, invalid GSTINs, IGST vs CGST / SGST against the place of supply, cash payments over ₹10,000, entries after the period, and a Benford first-digit test. Each with the rows and a reason, most serious first. | No |
| 3 | **Upload hub** | A client (or staff) drops many files or a zip at once; each file is recognised (bank statement, sales / purchase register, trial balance, GSTR-2B, broker P&L, Form 16, AIS, notice…), filed on the client, ticked off the checklist, and the right agent run on it. Also in the client portal. | Recognising PDFs / photos |
| 4 | **GSTR-1 preparation** | Sales register → B2B, B2CL, B2CS, exports, credit / debit notes, HSN summary and document summary, checked (GSTIN, place of supply vs tax type, rate, totals), in the GST offline tool's Excel layout. | No |
| 5 | **Financial statements** | Trial balance → Schedule III balance sheet and P&L (ledgers mapped by rules, the AI for the rest, corrections learned), key ratios, and the year-on-year review: big changes flagged with a question for the client. | Mapping unknown ledgers |
| 6 | **Depreciation** | Fixed asset register → Income-tax WDV by block (half rate when used under 180 days) and Companies Act SLM by useful life, with the difference for deferred tax. | No |
| 7 | **Balance confirmations** | Debtor and creditor balances → a confirmation request per party by email, replies tracked (agreed / differs, with the party's figure), a summary for the audit file. | Reading replies |

## Order
1 → 7, each built, tested, documented and committed before the next. Deploy when asked.

## Pricing
Part of the CA plan (agents switched on per firm); the upload hub counts towards the client portal's monthly clients.

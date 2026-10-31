# Document AI + Bookkeeping assistant (ROADMAP-V2 7.4, 9.5)

Receipts and bills arrive as photos or PDFs; Agentry reads them into typed fields, checks them with code, files the
confident ones and asks a person about the rest; then exports to Tally or a spreadsheet.

Code: `backend/src/agentry/documents.py` (Document AI, shared), `automations/bookkeeping/`, API
`api/routes/bookkeeping_api.py`, prompt `prompts/document_receipt/v2.md`, pages `/bookkeeping` and `/bookkeeping/[id]`,
migration 0026 (`app.documents`, card kind `document_review`). Samples: `mock-data/documents/` (`generate.py`).
Tests: `tests/test_bookkeeping.py`.

## How a document is read (Document AI)

1. **Store** the file (`var/documents/<org>/<id>.<ext>`, JPG/PNG/WEBP/PDF up to 10 MB) with its SHA-256.
2. **Read** with the `vision` model tier: vendor, GSTIN, bill number, date, currency, subtotal, CGST/SGST/IGST, total,
   category, payment method, description, plus the **line items** and a list of fields it had to **guess** (smudged,
   cut off, "?"). PDFs: their text if they have some, else the photo on the first page.
3. **Check with code** (the model's own confidence isn't trusted on its own):
   - required fields present (vendor, date, total, category);
   - line items add up to the subtotal or total; subtotal + taxes = total; CGST = SGST; not both CGST/SGST and IGST;
   - GSTIN format, state code and check digit (an online GST lookup is not done);
   - date not in the future, not over two years old;
   - the same file again (rejected), or the same vendor + bill number / date + total (flagged as a likely duplicate).
   Each failed check lowers the confidence of the fields involved; a guessed field is capped at 40%.
4. **Decide:** every required field at or above the business's threshold (default 85%) and no failed check → **Filed**;
   otherwise **Check** — a Needs-you card, and the document page highlights the doubtful fields next to the photo.

Seen in the live test: on a smudged café receipt the model read "7?0" as ₹770 with 98% confidence; the line-item check
(520 + 240 = 760) caught it and sent it to a person. The smudged date was read as the 22nd without being flagged:
reviewers should compare dates with the photo.

## Who does what

| Role | Sees | Acts |
|---|---|---|
| Owner, manager, finance | Bookkeeping page, receipt cards in Needs you | upload, check/fix/accept/reject, export |
| Viewer | Bookkeeping page | — |
| Front desk | — | — |

Bookkeeping cards follow the money (invoice) permission, like invoice follow-up, including card routing.

## Ways in

- **Portal:** upload one or many, or "Try 3 sample receipts".
- **WhatsApp / Telegram:** a photo or PDF sent to the business's number or bot. Settings → *Who may send receipts*:
  empty = anyone (a photo that isn't a bill goes to the assistant as before); otherwise only listed numbers / @usernames.
  The sender gets "Got it: FreshMart Supermarket, ₹1,254.76 on 28 Oct, filed under Groceries & pantry." (or that a person
  will check it / please send a clearer photo).
- **Email: not yet** (planned: attachments on a forwarding address).

## After filing

- **Budgets** (settings, per category per month): passing 80% sends `budget.alert` once a month (default rule
  "Budget alerts": owner + finance, Telegram/email).
- **Monthly summary** on the 1st at 09:00 IST: spending by category vs the month before, budgets, top vendors, what's
  still to check (`bookkeeping.monthly`, default rule "Monthly expenses"). Numbers come from code; the optional
  one-line observation is dropped if it contains a number that isn't in the summary.
- **Export:** *Export to Tally* (XML Purchase vouchers: party = vendor, expense ledger = category, Input CGST/SGST/IGST;
  expense = total − taxes so every voucher balances) or *CSV for Sheets*. Only filed documents, each exported once
  (the API's `include_exported=true` repeats them).

## Not built yet

Email intake, Google Sheets push (CSV today), the CA-firm view across its clients, a per-document billing meter, and an
online GSTIN lookup.

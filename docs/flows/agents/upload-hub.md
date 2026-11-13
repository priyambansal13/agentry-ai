# Upload hub (CA desk part 2, #3)

Everything a client sends, in one drop: many files or a zip. Each file is recognised, filed on the client, ticked off the
checklist it answers, and the right agent run on it, so the work is waiting when the team opens the client.

## Where
- Portal, on a **client's page**: "Drop many files or a zip" (open by default on a new client), or "Try a sample zip".
  Up to 40 files or 100 MB a batch. The batch opens as its own result: every file, what it was taken as, the checklist item
  ticked, and a link to the work each agent produced; anything skipped or failed says why. **Download Excel** lists it all.
- **Client portal** (`/portal/{token}`): "Something else to send?" now takes several files or a zip and runs them through
  the hub; the client sees only what each file was taken as (never the firm's agents). 20 files a day per link as before.
- Website: `/agents/ca-upload-hub` sorts a sample zip (recognition only: nothing stored, no AI).
- Available to every CA firm; each agent runs only when the firm has it switched on (otherwise the file is filed and the
  result says the agent isn't on).

## Steps
1. **Unpack**: zips opened, folders flattened, `__MACOSX` / hidden / Office lock files ignored. Refused inside a zip: password-
   protected files, a zip in a zip, files over 20 MB, anything compressed over 200:1 (a zip bomb). Over 40 files / 100 MB: the
   rest are listed to send separately.
2. **Same file**: a file whose SHA-256 is already on the client is not stored again ("already had it").
3. **Recognise**: spreadsheets and GSTR-2B JSON by their columns and title lines, in code (no AI cost): bank statement, broker
   P&L, payments register with TDS, sales / purchase register, ledger / day book, trial balance, fixed asset register, GSTR-2B.
   Anything else (PDFs, photos, text) by the document chaser's reader (name and text rules, the AI for the rest).
4. **File and tick**: through the document chaser when it's on (matched to the open filing's checklist, ticked; an unmatched
   file is a card for the firm), else stored with its type.
5. **Route**:

| Recognised as | Agent |
|---|---|
| GSTR-2B + a purchase register in the same batch | GST reconciliation (period from the 2B) |
| Bank statement | Bank statement classifier |
| Broker P&L | Capital gains |
| Payments register with TDS | TDS returns |
| Sales register (GST on) | GSTR-1 preparation |
| Purchase register, ledger, day book (and sales registers when GST is off) | Anomaly finder (with the client's GSTIN) |
| Form 16 / 16A / AIS / TIS / 26AS | Tax documents reader |
| Tax notice | Notice handler (reply card on the board) |
| Trial balance | Financial statements |
| Fixed asset register | Depreciation |
| GSTR-2B alone | kept for the next purchase register |

A failed agent run is reported on its file and never stops the rest of the batch.

## How it helps
No more downloading attachments, renaming files and working out which file is for which filing: one drop, the checklist
ticks itself, and the reconciliation, the bank classification, the anomaly scan and the notice reply are ready when the team
opens the client. Clients can send everything from their phone in one go.

## Code
`backend/src/agentry/automations/ca/hub.py` (`unpack`, `sniff`, `process`, `preview`, `sheet`, `sample_zip`); chaser
`receive(doc_type=…)` skips the model when the type is known; routes `POST /org/ca/clients/{cid}/hub(/sample)` and
`POST /public/portal/{token}/files/many` (`portal.upload_many`); website kind `upload-hub`; tests `backend/tests/test_ca_hub.py`.

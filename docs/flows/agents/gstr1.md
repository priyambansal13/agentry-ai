# GSTR-1 preparation (CA desk part 2, #4)

A client's sales register for the month becomes the GSTR-1 tables, checked first, in the layout of the GST offline tool's
Excel workbook. Fixed rules, no AI.

## Where
- Portal, on a **client's page**: Tools → GSTR-1 preparation (sales register + period, or "Try the sample"). The client's
  GSTIN gives their state. Comes with GST reconciliation (`ca_gst_reconciliation`).
- **Upload hub**: a sales register for a client with GST on goes straight to GSTR-1 preparation.
- **Download Excel**: sheets `b2b`, `b2cl`, `b2cs`, `cdnr`, `cdnur`, `exp`, `hsn(b2b)`, `hsn(b2c)`, `docs` (summary title on row 1,
  headings on row 4, data from row 5, as in the offline tool's workbook), plus `checks` and `totals`. Check the headings against
  the latest offline tool before importing: the portal changes them from time to time.
- Website: `/agents/ca-gstr1`, an editable 22-entry October register.

## Where each line goes
| Line | Table |
|---|---|
| Valid customer GSTIN | B2B (4A) |
| Unregistered, other state, invoice value above ₹1,00,000 (official figure `gst.b2cl_limit`) | B2CL (5) |
| Other unregistered (incl. an invalid GSTIN, flagged) | B2CS (7), summed by place of supply and rate |
| Place of supply 96 / other country, or a port code / shipping bill | EXP (6A): WPAY when IGST charged, else WOPAY |
| Credit / debit note (voucher type, or a CN / DN number) to a registered customer | CDNR (9B) |
| Note to an unregistered customer against a B2CL invoice (or above the limit), or an export | CDNUR (9B) |
| Other notes to unregistered customers | reduce / add to B2CS |
| Every line | HSN summary (12), split B2B / B2C; credit notes reduce it |
| Invoice and note series | Documents issued (13): first, last, total, cancelled = numbers missing from the series |

## Checks (most serious first)
- **high**: invalid GSTIN; the client's own GSTIN; IGST within the state or CGST + SGST to another state; CGST ≠ SGST; invoice
  number repeated, missing, over 16 characters or with characters the portal refuses; dated outside the month.
- **medium**: rate isn't a GST rate; 12% / 28% on an invoice from 22 Sep 2025 (slabs removed, except tobacco); invoice value ≠
  taxable + tax; HSN missing or under 4 digits.
- **low**: export without port / shipping bill; numbers missing from a series (counted as cancelled).
Flagged lines are still placed as the register says: the CA decides.

## Code
`backend/src/agentry/automations/ca/gstr1.py` (`prepare`, `compute`, `sheet`, `HEADS`); routes `/org/ca/clients/{cid}/gstr1(/sample)`
(agent `ca_gstr1`); website kind `gstr1`; tests `backend/tests/test_ca_gstr1.py`; sample `backend/samples/ca/sales_register_oct_sample.csv`.
The cleaner now reads "Invoice Value" / "Bill Amount" columns as numbers (only invoice / bill *numbers* stay text).

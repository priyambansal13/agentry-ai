# Excel cleaner (CA desk part 2, #1)

The messy sheet a client sends (a sales register, a ledger export, a party list) made clean in one click, with a list of
everything that was changed. Fixed rules, no AI: the same file always gives the same result.

## Where
- Portal: **Excel desk → Clean a messy sheet** (upload .xlsx / .csv, or "Try the sample"). The result opens on its own page and
  stays in the Excel desk's Recent list. **Download Excel** gives four sheets: Cleaned, Changes, To check, Similar names.
- Website: the **Excel cleaner** agent page (`/agents/ca-excel-cleaner`) has a try-it box on the same engine with an editable
  messy sales register.
- Switched on with the Excel desk (`excel_desk`); viewers can look but not run it.

## What it does, in order
1. **Finds the real header**: skips the firm's name, the report title and the period above it; joins two-line headers.
2. **Removes junk rows**: blank rows, Total / Sub-total / Opening / Closing balance / c/f / b/f lines, and the header repeated at
   each page break.
3. **Numbers**: "1,23,456.00", "₹5,000", "(1,200)", "1,200 Dr", "800 Cr" become numbers (brackets and Cr negative). A Debit and a
   Credit column also get one signed "Amount (Dr +, Cr −)" column; the originals stay.
4. **Dates**: one format (YYYY-MM-DD), including Excel date numbers. Read day first, as in India, unless the column itself proves
   month first (a second part above 12). A column where every date could be read either way is listed to check.
5. **GSTIN / PAN**: upper-cased and checked (GSTIN check digit, PAN pattern); wrong ones are listed, not changed.
6. **Phones**: Indian mobiles as +91XXXXXXXXXX. **Text**: spaces trimmed.
7. **Duplicates**: exact duplicate rows removed (the first kept).
8. **Similar names**: the same party written differently ("Sharma Traders Pvt Ltd", "SHARMA TRADERS") grouped; replaced by the most
   used spelling only when "Use one spelling for similar party names" is ticked.

Up to 20,000 rows. PDFs and photos are refused with a pointer to "PDF or photo to Excel" first.

## How it helps
An hour of retyping, Find & Replace and deleting total rows per client file becomes seconds, done the same way every time and
listed for the audit trail. Wrong GSTINs and PANs surface on day one instead of at GSTR-1 time, and the clean sheet is ready for
Tally import or the next agent (the anomaly finder, GSTR-1 preparation).

## Code
`backend/src/agentry/automations/ca/cleaner.py` (`clean`, `compute`, `sheet`); routes `POST /org/ca/excel/clean` and
`/excel/clean/sample` in `api/routes/ca_api.py` (saved in `app.ca_work` with agent `excel_cleaner`); website kind `excel-clean`
in `playground.py`; tests `backend/tests/test_ca_cleaner.py`. Sample: `backend/samples/ca/messy_sales_register_sample.csv`.

# Financial statements (CA desk part 2, #5)

A client's trial balance (this year, and last year when the sheet has it) becomes the Schedule III balance sheet and
statement of profit and loss, the ratios Schedule III asks for, and a list of questions for the client wherever a figure
moved a lot. Calculations by code; the AI only suggests a line for ledgers no rule covers, and those are marked for the CA.

## Where
- Portal, on a **client's page**: Tools → Financial statements (trial balance, or "Try the sample"). Upload hub: a trial
  balance goes here automatically. Any CA firm (shown with the filing tracker).
- The result page: checks, **ledgers to place or check** (a dropdown per ledger, "learn" ticked by default), balance sheet,
  profit and loss, questions for the client (copy all), ratios, and every ledger with where it went (any can be moved).
  **Download Excel**: Balance sheet, Profit and loss, Ratios, Questions for client, Mapping, Checks.
- Website: `/agents/ca-financial-statements`, an editable two-year trial balance of a private company (rules only).

## How ledgers are placed (first that applies)
1. The firm's **learned corrections** (`app.ca_ledger_map`, migration 0061): a ledger the firm placed by hand, by name.
2. **Name rules**: salaries / wages / PF → employee benefits; interest paid → finance costs; interest received, dividends →
   other income; depreciation; opening / closing stock; GST / TDS → other current liabilities or assets by balance;
   provision for tax → short-term provisions; income-tax expense → tax; OD / CC → short-term borrowings; deposits, prepaid…
3. **Tally group rules**: Capital Account, Reserves & Surplus, Secured / Unsecured Loans, Bank OD, Sundry Creditors, Duties &
   Taxes, Provisions, Current Liabilities, Fixed Assets, Investments, Stock-in-Hand, Sundry Debtors, Cash / Bank, Deposits,
   Loans & Advances, Sales / Purchase Accounts, Direct / Indirect Expenses and Incomes. A balance-sheet group beats a P&L-
   sounding name ("Salary Payable" under Current Liabilities stays a liability).
4. **The AI** for what's left (prompt `ca_ledger_map`): only keys from the list are accepted; shown as "AI: check".
5. Anything else is **not placed**: listed, kept out of the totals, and the balance-sheet difference says so.

A bank account in credit is shown as a short-term borrowing. Closing stock is the inventories line and is credited to the
change in inventories (Tally leaves it out of the trial balance totals). Profit after tax goes to reserves (a company) or
capital (a firm, proprietor, LLP), so the balance sheet balances when the trial balance does.

## Checks, ratios, questions
- Checks: trial balance not balancing (each year); balance sheet out (and why); unplaced ledgers; suspense; AI placements;
  debtors in credit / creditors in debit; cash in credit.
- Ratios (Schedule III, 2021 amendment): current, debt-equity, ROE, inventory / receivables / payables turnover, net capital
  turnover, net profit, ROCE; a change over 25% is marked "explain".
- Questions: a line or a P&L ledger that moved over 25% and over max(1% of revenue, ₹50,000) gets a plain question (e.g.
  receivables vs sales growth, rent up 60%, OD up 52%).

## Code
`backend/src/agentry/automations/ca/finstat.py` (`read`, `rule_line`, `map_ledgers`, `build`, `prepare`, `correct`, `sheet`);
routes `/org/ca/clients/{cid}/financials(/sample)`, `POST /org/ca/work/{wid}/ledger`; agent `ca_financial_statements`; website
kind `financials`; tests `backend/tests/test_ca_finstat.py`; sample `backend/samples/ca/trial_balance_sample.csv` (both years
consistent: last year's closing reserves = this year's opening).

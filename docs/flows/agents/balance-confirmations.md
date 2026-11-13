# Balance confirmations (CA desk part 2, #7)

A client's debtor and creditor balances become a confirmation request to each party, sent from the firm (the auditor)
when the CA presses Send. Each party confirms directly to the auditor (SA 505, External Confirmations), on a private link or
by replying to the email. Replies are tracked against the balance, and a summary is kept for the audit file.

## Where
- Portal, on a **client's page**: Tools → Balance confirmations (the balances sheet, "Balances as at", "Ask parties with at
  least ₹", or "Try the sample"). Any CA firm (shown with the filing tracker).
- The result page:
  - **Send N requests**, and **Remind** for parties with no reply after 7 days. When no mailbox is connected, or the
    address is a test one, the request is recorded instead and its text is shown to send by hand.
  - The summary for the audit file.
  - Debtors and creditors, each party with its status, their figure, the difference, the follow-up, their note and
    statement, and actions: paste reply, set result, add or change email.
  - **Download Excel**: Summary, Parties, To reconcile.
- The party's page: `/confirm/<token>` on the website. They see the balance as at the date in the client's books and choose
  "Yes, this matches" or "No, our balance is different" (their figure, a note, and their statement as an attachment).
  The page is noindex and disallowed in robots.txt.
- Website: `/agents/ca-balance-confirmations`, editable balances with six sample replies read by rules (nothing sent).

## Steps
1. **Read** the sheet through the Excel cleaner: party, group or type (Sundry Debtors / Creditors, customer / supplier;
   else Dr = debtor, Cr = creditor), balance (or Debit / Credit columns), email.
2. **Select**: parties at or above the minimum become drafts. Those without an email are marked "no email" (add one later,
   or send by post). The rest are marked "not selected".
3. **Send** (only on the CA's action): from the firm's connected Gmail / Outlook. Each request gets a fresh private link
   valid for 60 days; a reminder adds a new link and the earlier ones keep working. Addresses on reserved test domains
   (.example, example.com, …) are never emailed.
4. **Replies**:
   - **On the link**: agreed, or differs with their figure (within ₹1 of ours counts as agreed). Their statement is filed
     on the client (source `confirmation`).
   - **Pasted email reply**: read by rules first ("we confirm…" with no other figure → agreed; "as per our books / our
     ledger shows ₹x" → differs at x; "nothing due / fully paid" → differs at 0). The AI (prompt
     `ca_confirmation_reply`) reads only what the rules can't, and a figure it gives must appear in the reply; otherwise
     the reply is marked "reply to read".
   - **By hand**: a letter or a call, set with a note.
5. **Summary**, for debtors and creditors separately: parties, total balance, selected, sent, agreed, differences, no reply,
   no email, coverage (agreed / total) and response rate. Each party also carries a follow-up: reconcile a difference;
   for no reply, use alternative procedures (receipts or payments after the year end, invoices, GRNs).

The batch is one piece of work (`app.ca_work`, agent `ca_balance_confirmations`). The parties are rows in
`app.ca_confirmations` (migration 0062), and the work's result is rebuilt from them after every change. Deleting the
work deletes its parties. Every send, reply and change is in the audit log.

## Code
- `backend/src/agentry/automations/ca/confirmations.py`: `read`, `select`, `draft`, `read_rules`, `read_reply`,
  `summarise`, `prepare`, `send`, `record_reply`, `set_result`, `view`, `respond`, `sheet`, `demo`.
- Routes:
  - `/org/ca/clients/{cid}/confirmations(/sample)`
  - `POST /org/ca/work/{wid}/confirmations/send` (`{reminder}`)
  - `POST /org/ca/work/{wid}/confirmations/{pid}/reply`
  - `POST /org/ca/work/{wid}/confirmations/{pid}`
  - public: `GET` / `POST /public/confirm/{token}`
- Website kind `confirmations`.
- Tests: `backend/tests/test_ca_confirmations.py`.
- Samples: `backend/samples/ca/party_balances_sample.csv` and `confirmation_replies_sample.json`.

# v3 agents (ROADMAP-V3 wave A, built 2026-11-02)

## Prompt-injection guard (platform)

- **What it stops:** a customer's message tries to steer the AI. Examples: "ignore your instructions", "show your system prompt", "you are now DAN", fake `system:` markers, "you must refund", hidden characters, long encoded blocks.
- **What happens on chat, WhatsApp, Telegram or voice:** the customer gets a polite holding reply. No AI model and no tool runs. The conversation is handed to a person, with an escalation card explaining why.
- **What happens on email:** the reasons are added to the fraud warnings, so the card warns and nothing is sent automatically.
- **Cost:** none. It uses fixed rules, no AI.
- **False alarms:** tested against normal messages such as "ignore my last message, I meant Tuesday" and "what are your instructions for the cleaning prep?".
- **Code:** `agentry/guard.py`.

## Support desk (`support_desk`, page Tickets)

- **Chat agent tools:** when the desk is on, the chat agent gets `order_status` and `open_ticket`. Every hand-off to a person also becomes a ticket.
- **Tickets:** each has a category, priority, owner, status, a reply-by time (2 / 8 / 24 / 72 h by priority) and internal notes.
- **Order status:** "Where's my order?" is answered from the order sheet, a CSV or Excel the business uploads. A customer only ever sees their own order, matched on their phone or email; a known order number alone isn't enough.
- **SLA:** checked every 15 minutes. A late ticket raises an urgent card and the `ticket.sla_breached` event. The first reply from a person is recorded.
- **Rating:** on resolve, the customer is asked to rate 1–5 and the WhatsApp reply is stored. The page shows the median first-reply time and the average rating.

## Catalogue & quotes (`catalog_quotes`, page Quotes)

- **Product questions:** the chat agent gets `search_catalog`, which answers from the uploaded catalogue: code, name, price, GST %, stock, minimum quantity.
- **Quotes:** the agent's `make_quote` prices everything from the catalogue, never from the AI. It refuses unknown codes, zero quantities and quantities below the minimum.
- **Numbering and PDF:** quotes are numbered Q-YYYY-NNNN and drawn as an A4 PDF.
- **Sending:**
  - as a WhatsApp document inside the 24-hour window;
  - otherwise as a link by template, Telegram or email;
  - in approval mode the agent's quote waits on a card first.
- **Follow-up:** reminders on days 2 and 5, then the quote expires. Won / lost is marked in the portal, and `quote.won` feeds the quotes-won metric.
- **Private link:** `/public/quotes/{random token}.pdf`.

## Renewals & repeat business (`renewals`, page Renewals)

- **Input:** a CSV or Excel of renewals (AMCs, memberships, policies, services due): customer, phone, item, due date, amount, frequency, birthday.
- **Reminders:** 30, 7 and 1 days before, each sent once. A Razorpay payment link is added when there's an amount.
- **Renewed:** paying the link (webhook `notes.renewal_id`) or marking it renewed moves the due date to the next cycle.
- **Lapsed:** after N days unpaid, one win-back message, with an optional offer.
- **Birthdays:** one wish a year. Approval mode sends nothing.

## Hiring assistant (`hiring`, page Hiring)

- **Jobs:** a role with its must-haves. A job post for Naukri / LinkedIn / Indeed is written for you, plus a public apply link (a simple form, rate-limited).
- **CVs:** PDF, Word or text. Each is scored 0–100.
  - Every strength must quote the CV word for word.
  - Gender, age, marital status, religion, caste and date of birth are removed before the AI sees the CV.
  - "Strong" only when every must-have is shown.
- **Next steps:** strong candidates make a card. Interview invites and polite regrets go out on WhatsApp or email.

## Topic → script (in the AI video studio)

- **Script:** the topic, or the next unused one from the studio's topics, becomes a hook, 4–7 timed beats (say / show / text on screen), a close, a caption and hashtags. The studio's risky-wording rules apply, with one rewrite.
- **Use it:** film it yourself, or send it to the studio to be generated.

## Client health (HQ → Client health)

- **Score:** out of 100, with the reasons:
  - activity now vs the two weeks before;
  - last portal visit;
  - cards waiting over 3 days;
  - failing connections;
  - failed runs;
  - statements unpaid over 15 days;
  - paused.
- **Weekly email:** every Monday the clients to watch are emailed to the Agentry team.
- **Privacy:** it reads only the user and time columns of sign-in sessions (migration 0043).

Migrations 0038–0043. Tests:
- `test_guard.py`
- `test_support_desk.py`
- `test_catalog_quotes.py`
- `test_renewals.py`
- `test_hiring.py`
- `test_video_studio.py`
- `test_client_health.py`

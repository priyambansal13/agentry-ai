# Agentry flows

How Agentry works end to end, as built today. Each file has a flow diagram (Mermaid, rendered by GitHub and most editors), the steps in order, and who does what.

Read in this order:

| # | Flow | What it covers |
|---|---|---|
| 1 | [Sales: demo, proposal, plan](01-sales-demo-proposal.md) | A prospect fills in the website form → demo → follow-ups → reply → proposal → becomes a client |
| 2 | [Client onboarding](02-client-onboarding.md) | Creating the client in HQ, invitations, the setup steps, go-live, the team |
| 3 | [Billing and statements](03-billing.md) | Plans, monthly statements, evidence, disputes, payment, margin |
| 4 | Agents, one file each: | |
| | [Lead engine (shared)](agents/lead-engine.md) | One contact per person, one agent per lead, opt-outs: what every lead agent shares |
| | [Inbox triage](agents/inbox-triage.md) | Gmail sorted, urgent alerts and escalation, reply drafts, digest |
| | [Website chat agent](agents/website-chat.md) | The chat bubble on the client's site: answers, qualifies, books, hands off |
| | [WhatsApp assistant](agents/whatsapp-assistant.md) | The same agent on the client's WhatsApp number |
| | [Invoice follow-up](agents/invoice-follow-up.md) | Reminders on days 7/14/21/28, replies understood, payments matched |
| | [Lead reactivation](agents/lead-reactivation.md) | Old leads messaged again, paced, replies booked |
| | [Speed-to-lead](agents/speed-to-lead.md) | A form lead gets a message within a minute |
| | [AI receptionist (voice)](agents/ai-receptionist.md) | Phone and browser calls answered, recorded, summarised, call-back cards |
| | [Personal cold email](agents/cold-email.md) | Prospect lists, decision makers, fact-checked first lines, review (sending: next) |

**Roles used everywhere.** Client roles come from `config/roles.json`; Agentry staff can do everything, and every staff action is audited.

| Role | In one line |
|---|---|
| **Agentry admin / staff** | Sells, sets up and runs clients from Agentry HQ; can open any client's portal |
| **Owner** | The client's boss: everything in their portal, including team, billing and connections |
| **Manager** | Day-to-day work and settings; no team or billing |
| **Front desk** | Works the queue: approves drafts, replies, books |
| **Finance** | Invoices, payments, statements |
| **Viewer** | Reads reports only |

Source of truth for details: [CLIENT-ONBOARDING.md](../CLIENT-ONBOARDING.md) (role tables per agent), the agent specs in [automations/](../automations/), and the phase plans.

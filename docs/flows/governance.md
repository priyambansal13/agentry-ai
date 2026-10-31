# Governance: autonomy, limits, audit, evals

How much the agents may do on their own, and how we can prove what happened. ROADMAP-V2 §2.2.

## Autonomy levels (Automations → Autonomy & limits)

| Level | What happens |
|---|---|
| **Watch only** | The agent works it out and records what it would have done (the message is kept on the run). Nothing is sent, no card |
| **Suggest** | A Needs-you card; a person approves, edits or discards |
| **Act within limits** | Goes out on its own up to the daily limit and never 9 pm–8 am (for messages the business starts); the rest become cards, saying why ("today's limit of 50 reached", "quiet hours") |
| **Act** | Goes out on its own; the daily limit still applies |

| Action | Starts as | Limits by default |
|---|---|---|
| Send payment reminders | the agent's approval/live switch (approval → Suggest, live → Act within limits) | 50/day, quiet hours |
| Send win-back messages to old leads | same | 100/day, quiet hours |
| Message new leads within a minute | same | 100/day (no quiet hours: they just asked) |
| Send email replies without review (trusted categories) | same; and only for categories with 10+ drafts approved as written | 20/day |
| Send cold emails | Act within limits (each first line is approved first; Suggest isn't offered) | 150/day for the business, on top of each mailbox's ramp-up cap |

So nothing changes on day one. **The owner** changes levels and limits; managers can look. Each action shows its track
record over 30 days (cards approved as written / edited / discarded) and a suggestion:
- *more freedom* after 20+ decisions with 90%+ approved as written;
- *ask again* if people keep changing or discarding drafts sent on autopilot.

## The audit log can't be quietly changed

Every audit entry stores a hash of itself plus the entry before it, per business, computed by the database on insert.
The app can't update or delete entries. If someone with database access edits or deletes one, the chain breaks at that
entry. HQ → client shows "✓ Audit log intact (N entries)", or where it breaks.

## Eval gate

`backend/config/eval-gates.yaml` lists each prompt with its labelled set and minimum accuracy:

| Prompt | Data | Gate | Last measured |
|---|---|---|---|
| Inbox triage classifier | 20 held-out emails (category + urgent) | 85% | 95% |
| Invoice reply classifier | 20 replies | 85% | 95% |

Run `cd backend && uv run agentry eval-gate`. GitHub runs it on pull requests that touch prompts or the model gateway
(`.github/workflows/eval-gate.yml`). It needs repository secret `OPENAI_API_KEY` and variables `AGENTRY_MODEL_FAST` /
`AGENTRY_MODEL_WRITER`; without them it skips and says so.

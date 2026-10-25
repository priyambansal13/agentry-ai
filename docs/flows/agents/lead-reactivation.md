# Lead reactivation

Messages old leads and past customers again ("hi again"), paced so it never looks like a blast, and books the ones who reply.

## Setup

1. **Import old leads**: CSV/Excel (Leads page). Each row becomes one contact (duplicates merged), with consent recorded where it exists.
2. **Connect** WhatsApp and/or Gmail.
3. **Settings**: messages per hour (default 20), an offer you're happy to mention.
4. Persona, compliance, **go live**.

## Diagram

```mermaid
flowchart TD
  IMP["Old leads imported"] --> CAMP["Owner/manager starts a campaign<br/>(name + messages per hour)"]
  CAMP --> SL["Each lead gets a slot (paced)"]
  SL --> CK{"May we contact them?<br/>consent, not suppressed, no other agent busy with them"}
  CK -- no --> SK["Skipped (reason recorded)"]
  CK -- yes --> M1["Message 1 'hi again'<br/>WhatsApp first, else email"]
  M1 --> W3["3 days"]
  W3 --> R1{"Replied?"}
  R1 -- no --> M2["Message 2 (light follow-up)"]
  R1 -- yes --> AG["The assistant takes over:<br/>re-qualifies and books"]
  M2 --> R2{"Replied?"}
  R2 -- yes --> AG
  R2 -- no --> END["Campaign done for this lead"]
  AG --> BK["Booked → result on the statement"]
  R1 & R2 -->|"stop"| OO["Opted out everywhere"]
```

## Who does what

| | Owner | Manager | Front desk | Finance | Viewer | Agentry |
|---|---|---|---|---|---|---|
| Import leads, start / pause campaigns | ✓ | ✓ | | | | ✓ |
| See campaigns and progress | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| Approve messages (approval mode), reply, book | ✓ | ✓ | ✓ | | | ✓ |

**Note:** promotional messages by phone (voice reactivation) stay off until DLT registration is done (India).

**Code:** `automations/lead_reactivation`, `sequences.py`, `leads.py`. Spec: [lead-reactivation.md](../../automations/lead-reactivation.md).

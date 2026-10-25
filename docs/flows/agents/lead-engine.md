# Lead engine (shared by every lead agent)

Not an agent you sell on its own: the shared base under website chat, WhatsApp, speed-to-lead, reactivation, inbox triage and the receptionist. It makes sure **one person is one contact**, **only one agent talks to them at a time**, and **"stop" stops everything**.

## Diagram

```mermaid
flowchart TD
  IN["A person arrives: form · website chat · WhatsApp ·<br/>email · phone call · old-leads CSV"] --> RC["Find or create ONE contact<br/>(phone in E.164 first, then email)"]
  RC --> LD["Lead with a stage:<br/>new → contacted → engaged → qualified → booked → won / lost"]
  LD --> CL{"Which agent may talk to them now?"}
  CL -->|"they wrote or called in"| INB["The agent they contacted takes over"]
  CL -->|"warmer / higher priority agent"| HP["Takes over from a colder one"]
  CL -->|"current owner idle 14 days"| ID["Free for another agent"]
  CL -->|"otherwise"| NO["Stays with its current agent"]
  INB & HP & ID --> OUT{"Before any outbound message"}
  OUT --> CC{"Suppressed? Consent needed<br/>(WhatsApp, SMS, voice) and given?"}
  CC -- no --> SKIP["Not sent (reason recorded)"]
  CC -- yes --> SEND["Message sent"]
  SEND --> RP["Reply"]
  RP --> OO{"'stop' / 'unsubscribe' /<br/>'band karo' / 'mat bhejo'?"}
  OO -- yes --> STOP["Opted out everywhere:<br/>consent revoked, address suppressed,<br/>sequences stopped, lead opted_out"]
  OO -- no --> AG["The owning agent answers, qualifies, books"]
  AG --> BK["Booked → outbound sequences end"]
```

## Rules

| Rule | How |
|---|---|
| **One contact per person** | Phones normalised to international format using the client's country; emails lower-cased; matched by phone first, then email. Duplicates can be merged |
| **One voice** | Each lead has one owning agent. Priority (high → low): receptionist 60, website chat 50, WhatsApp 45, speed-to-lead 40, inbox triage 35, invoice follow-up 30, reactivation 20, cold email 10. Someone writing in always takes over; an owner idle for 14 days lets go |
| **Consent** | WhatsApp, SMS and voice need recorded consent (form opt-in with time and source). Email to businesses relies on legitimate interest plus unsubscribe |
| **Opt-out** | "stop" on its own, or clear phrases anywhere ("unsubscribe", "remove me from", "stop messaging", "band karo", "mat bhejo") → consent revoked, address suppressed, all sequences stopped, lead stage *opted out*. "Stop by tomorrow" is not an opt-out |
| **Finished stages** | won, lost, disqualified, opted out: no agent will contact them |

## Who sees leads

| | Owner | Manager | Front desk | Finance | Viewer | Agentry |
|---|---|---|---|---|---|---|
| Leads page | ✓ | ✓ | ✓ | | | ✓ |
| Import old leads, lead forms | ✓ | ✓ | | | | ✓ |

**Code:** `backend/src/agentry/leads.py`, `sequences.py`.

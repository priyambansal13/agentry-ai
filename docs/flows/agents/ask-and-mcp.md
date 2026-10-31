# Ask your business + the Agentry MCP server (ROADMAP-V2 9.1 part 2, 2.6)

Plain questions ("what's overdue?", "how many leads this week?", "what's on tomorrow?") answered from the business's own
data, in the portal (**Ask**), on the Telegram team bot (any message that isn't a command), and from Claude Desktop,
ChatGPT or any MCP app.

Code: `backend/src/agentry/copilot.py`, `api/routes/copilot_api.py`, page `/ask`, migration 0030 (`app.api_tokens`).
Tests: `tests/test_copilot.py`.

## How an answer is made

- The `writer` model gets the question and a fixed set of **read-only tools**: money summary, overdue invoices, leads,
  appointments, Needs you, conversations, expenses, reviews, find a customer. Each tool is a query written in code,
  run inside the business's own data (row-level security). The model never writes SQL and can't change anything.
- **Permissions:** a person only gets the tools their role allows (front desk: no money; finance: no conversations or
  leads), every call is checked again, a customer lookup shows invoice counts only to people with money access, and the
  model is told which areas are outside the person's role so it says so instead of working around it.
- Up to 4 rounds of tool calls; every number must come from a tool result. Each question is an agent run (Runs).
- Without a model (tests, outages) a keyword route picks one tool and shows its result.

## MCP server (Claude Desktop, ChatGPT…)

- **Ask → Use with Claude or ChatGPT → Create a token.** The token (`agt_…`) is shown once with a ready config:
  ```json
  {"mcpServers": {"agentry": {"type": "http", "url": "https://api.agentry.duckdns.org/mcp",
                              "headers": {"Authorization": "Bearer agt_…"}}}}
  ```
- `POST /mcp` speaks MCP over Streamable HTTP (JSON-RPC: initialize, tools/list, tools/call, ping). Tools are marked
  read-only. The token's owner and business are looked up on every call with their **current** role: change their role
  or remove them, and the token follows at once. Revoke a token from the same page. Only a SHA-256 of a token is stored;
  creating and revoking are in the audit log.

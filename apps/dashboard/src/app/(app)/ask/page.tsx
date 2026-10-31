import { Card } from "@agentry/ui";
import { AskChat, McpTokens } from "@/components/ask";
import { api, requirePage } from "@/lib/session";

export const metadata = { title: "Ask your business" };

export default async function AskPage() {
  const active = await requirePage("ask");
  const tokens = await api<{ items: { id: string; name: string; prefix: string; created_at: string; last_used_at: string | null }[]; mcp_url: string }>(
    "/org/api-tokens", { orgId: active.id });
  return (
    <div className="space-y-6">
      <header>
        <h1 className="font-display text-3xl font-bold tracking-tight">Ask your business</h1>
        <p className="mt-1 text-muted">Plain questions, answered from {active.name}&apos;s own numbers. It can only read: nothing is sent or changed. You can also ask your Agentry Telegram bot.</p>
      </header>
      <Card className="p-5"><AskChat /></Card>
      <Card className="p-5">
        <h2 className="mb-2 font-display text-lg font-bold">Use with Claude or ChatGPT</h2>
        <McpTokens tokens={tokens.items} mcpUrl={tokens.mcp_url} />
      </Card>
    </div>
  );
}

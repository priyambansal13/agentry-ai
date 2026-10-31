"use client";

import { Button, Input, Label } from "@agentry/ui";
import { useRouter } from "next/navigation";
import { useState, useTransition } from "react";
import { askBusiness, createApiToken, revokeApiToken } from "@/app/(app)/actions";

type Turn = { role: "user" | "assistant"; content: string; tools?: string[] };
const EXAMPLES = ["What's overdue and who owes the most?", "How many new leads came in this week, and from where?",
                  "What appointments do we have tomorrow?", "What's waiting for me in Needs you?", "How were our reviews this month?"];

/** Ask your business: questions in plain words, answered from your own data (read-only). */
export function AskChat() {
  const [turns, setTurns] = useState<Turn[]>([]);
  const [q, setQ] = useState("");
  const [pending, start] = useTransition();
  function ask(question: string) {
    if (!question.trim()) return;
    const history = turns.map(({ role, content }) => ({ role, content }));
    setTurns((t) => [...t, { role: "user", content: question }]);
    setQ("");
    start(async () => {
      const r = await askBusiness(question, history);
      setTurns((t) => [...t, r.ok ? { role: "assistant", content: r.data.answer, tools: r.data.tools } : { role: "assistant", content: `Sorry: ${r.error}` }]);
    });
  }
  return (
    <div className="space-y-4">
      {turns.length === 0 && (
        <div className="flex flex-wrap gap-2">
          {EXAMPLES.map((e) => (
            <button key={e} type="button" onClick={() => ask(e)} className="rounded-full border-2 border-line px-3 py-1.5 text-sm hover:border-ink">{e}</button>
          ))}
        </div>
      )}
      <div className="space-y-3" aria-live="polite">
        {turns.map((t, i) => (
          <div key={i} className={t.role === "user" ? "ml-auto max-w-[85%] rounded-2xl bg-lime-soft px-4 py-2" : "max-w-[85%] rounded-2xl border-2 border-line bg-card px-4 py-3"}>
            <p className="whitespace-pre-line text-sm">{t.content}</p>
            {t.tools && t.tools.length > 0 && <p className="mt-1 text-xs text-muted">Looked at: {t.tools.map((x) => x.replace(/_/g, " ")).join(", ")}</p>}
          </div>
        ))}
        {pending && <p className="text-sm text-muted">Looking it up…</p>}
      </div>
      <form onSubmit={(e) => { e.preventDefault(); ask(q); }} className="flex gap-2">
        <Input aria-label="Your question" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Ask about money, leads, appointments, reviews…" className="flex-1" />
        <Button type="submit" disabled={pending || !q.trim()}>Ask</Button>
      </form>
    </div>
  );
}

type Token = { id: string; name: string; prefix: string; created_at: string; last_used_at: string | null };

/** Personal tokens for Claude Desktop / ChatGPT (the Agentry MCP server). The token is shown once. */
export function McpTokens({ tokens, mcpUrl }: { tokens: Token[]; mcpUrl: string }) {
  const router = useRouter();
  const [pending, start] = useTransition();
  const [name, setName] = useState("Claude Desktop");
  const [fresh, setFresh] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const config = fresh ? JSON.stringify({ mcpServers: { agentry: { type: "http", url: mcpUrl, headers: { Authorization: `Bearer ${fresh}` } } } }, null, 2) : "";
  return (
    <div className="space-y-4 text-sm">
      <p className="text-muted">Ask the same questions from Claude Desktop, ChatGPT or any MCP app. Read-only, with your own permissions. Server address: <code>{mcpUrl}</code></p>
      {fresh && (
        <div className="space-y-2 rounded-xl border-2 border-ink p-3">
          <p className="font-semibold">Copy your token now: it won&apos;t be shown again.</p>
          <code className="block break-all rounded bg-paper p-2">{fresh}</code>
          <p className="text-muted">For Claude Desktop (Settings → Developer → Edit config), or any app that takes an MCP server with a header:</p>
          <pre className="overflow-x-auto rounded bg-paper p-2 text-xs">{config}</pre>
        </div>
      )}
      <ul className="divide-y divide-line">
        {tokens.map((t) => (
          <li key={t.id} className="flex flex-wrap items-center justify-between gap-2 py-2">
            <span><strong>{t.name}</strong> <span className="text-muted">({t.prefix}…) · {t.last_used_at ? `last used ${new Date(t.last_used_at).toLocaleDateString("en-IN")}` : "not used yet"}</span></span>
            <Button size="sm" variant="ghost" disabled={pending} onClick={() => confirm(`Revoke "${t.name}"? Apps using it stop working.`) && start(async () => {
              await revokeApiToken(t.id); router.refresh();
            })}>Revoke</Button>
          </li>
        ))}
      </ul>
      <form onSubmit={(e) => { e.preventDefault(); start(async () => {
        const r = await createApiToken(name);
        if (r.ok) { setFresh(r.data.token); setErr(null); router.refresh(); } else setErr(r.error);
      }); }} className="flex flex-wrap items-end gap-2">
        <div><Label htmlFor="tok-name">Name</Label><Input id="tok-name" value={name} onChange={(e) => setName(e.target.value)} /></div>
        <Button type="submit" variant="secondary" disabled={pending || name.trim().length < 2}>Create a token</Button>
        {err && <span role="status" className="text-danger">{err}</span>}
      </form>
    </div>
  );
}

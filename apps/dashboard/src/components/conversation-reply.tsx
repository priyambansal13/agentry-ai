"use client";

import { Badge, Button, Textarea } from "@agentry/ui";
import { useRouter } from "next/navigation";
import { useEffect, useState, useTransition } from "react";
import { replyInConversation, setConversationStatus } from "@/app/(app)/actions";

const WHERE: Record<string, string> = {
  web_chat: "The visitor sees your reply in the chat window on your website.",
  whatsapp: "Sent from your WhatsApp Business number (only within 24 hours of their last message).",
  email: "Sent from your connected Gmail, in the same thread.",
};

export function ConversationReply({ id, channel, status, agentChannel }: { id: string; channel: string; status: string; agentChannel: boolean }) {
  const router = useRouter();
  const [body, setBody] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const [pending, start] = useTransition();
  // a person is talking to the visitor: keep the page fresh so their next messages appear
  useEffect(() => {
    if (status !== "handed_off" || channel !== "web_chat") return;
    const t = window.setInterval(() => router.refresh(), 5000);
    return () => window.clearInterval(t);
  }, [status, channel, router]);
  const act = (fn: () => Promise<{ ok: boolean; error?: string }>, after?: () => void) => start(async () => {
    const r = await fn();
    if (!r.ok) return setErr(r.error ?? "Something went wrong");
    setErr(null); after?.(); router.refresh();
  });
  return (
    <div className="space-y-3 rounded-2xl border-2 border-line bg-card p-4">
      {agentChannel && (
        <div className="flex flex-wrap items-center justify-between gap-2">
          {status === "handed_off"
            ? <Badge tone="warning">You&apos;re handling this chat: the agent is paused here</Badge>
            : status === "closed" ? <Badge>Closed</Badge> : <Badge tone="lime">The agent is answering</Badge>}
          {status === "handed_off"
            ? <Button size="sm" variant="secondary" disabled={pending} onClick={() => act(() => setConversationStatus(id, "open"))}>Hand back to the agent</Button>
            : <Button size="sm" variant="secondary" disabled={pending} onClick={() => act(() => setConversationStatus(id, "handed_off"))}>Take over</Button>}
        </div>
      )}
      <form onSubmit={(e) => { e.preventDefault(); act(() => replyInConversation(id, body), () => setBody("")); }} className="space-y-2">
        <Textarea aria-label="Your reply" rows={3} required value={body} onChange={(e) => setBody(e.target.value)} placeholder="Write a reply…" />
        <div className="flex flex-wrap items-center justify-between gap-2">
          <p className="text-xs text-muted">{WHERE[channel] ?? ""}</p>
          <Button type="submit" disabled={pending || !body.trim()}>Send reply</Button>
        </div>
        {err && <p role="alert" className="text-sm text-danger">{err}</p>}
      </form>
    </div>
  );
}

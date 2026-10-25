import { Badge, Card, cn } from "@agentry/ui";
import Link from "next/link";
import { notFound, redirect } from "next/navigation";
import { CategoryPicker } from "@/components/category-picker";
import { ConversationReply } from "@/components/conversation-reply";
import { DeleteRecordingButton } from "@/components/voice-settings";
import { approvalKinds, categoryTone, formatDateTime } from "@/lib/format";
import { can, canOnItem } from "@/lib/permissions";
import { api, ApiError, getActiveOrg, requirePage, getMe } from "@/lib/session";

export const metadata = { title: "Conversation" };

type Msg = {
  id: string; direction: "in" | "out"; author: string; body: string; created_at: string;
  metadata: { from?: string; body_deleted_at?: string; sent_from?: string; mailbox?: string;
              attachments?: { filename: string; size: number; text?: string }[];
              triage?: { category: string; urgent?: boolean; urgent_reason?: string; summary?: string; source?: string; model?: string;
                         suspicious?: boolean; risk?: string[] };
              tools?: { tool: string; args: Record<string, unknown> }[]; booking?: { service: string; when: string; staff: string } | null;
              delivery?: "sent" | "delivered" | "read" | "failed" | "recorded"; delivery_error?: string | null;
              sent_by?: { user_id: string; name: string; staff?: boolean } };
};
type Detail = {
  conversation: { id: string; channel: string; automation_key: string | null; subject: string | null; status: string; contact_name: string | null;
                  contact_email: string | null; contact_phone: string | null; metadata: { labels?: string[]; draft?: string; test?: boolean; recording?: string | null; recording_deleted?: { at: string; reason: string }; duration_seconds?: number; ended_at?: string;
                              call?: { summary: string; intent: string | null; outcome: string; follow_up: boolean; follow_up_reason: string | null } } };
  messages: Msg[]; approvals: { id: string; kind: string; status: string; title: string }[];
  bookings: { starts_at: string; service: string; staff: string; status: string }[];
};

const TOOL_LABELS: Record<string, string> = {
  search_knowledge: "looked up knowledge", check_availability: "checked the calendar", book_appointment: "booked",
  save_lead: "saved lead details", handoff_to_human: "asked a person to take over",
};

const OUTCOME: Record<string, { label: string; tone: "success" | "lime" | "warning" | "neutral" }> = {
  booked: { label: "Booked", tone: "success" }, answered: { label: "Answered", tone: "lime" }, handed_off: { label: "Asked for a person", tone: "warning" },
  message_taken: { label: "Message taken", tone: "warning" }, no_conversation: { label: "No conversation", tone: "neutral" },
};

export default async function ConversationPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const [active, me] = await Promise.all([getActiveOrg(), getMe()]);
  const sender = (by?: { user_id: string; name: string; staff?: boolean }) =>
    !by ? "Your team" : by.user_id === me.user.id ? "You" : by.staff ? `${by.name} (Agentry)` : by.name;
  await requirePage("conversations");
  if (!active) redirect("/home");
  let d: Detail;
  try {
    d = await api(`/org/conversations/${id}`, { orgId: active.id });
  } catch (e) {
    if (e instanceof ApiError && e.status === 404) notFound();
    if (e instanceof ApiError && e.status === 403) redirect("/home");
    throw e;
  }
  const c = d.conversation;
  const canAct = me.is_staff || canOnItem(active.role, c.automation_key, "act");
  const canConfigure = me.is_staff || can(active.role, "automation", "configure");
  const hasGmail = c.channel !== "email" || (await api<{ items: { provider: string; status: string }[] }>("/org/connections", { orgId: active.id }))
    .items.some((x) => x.provider === "gmail" && x.status === "connected");
  const triageCfg = c.automation_key === "inbox_triage" && canAct
    ? await api<{ items: { template_key: string; config: { categories?: string[]; custom_categories?: string[] } }[] }>("/org/automations", { orgId: active.id })
        .then((r) => r.items.find((x) => x.template_key === "inbox_triage")?.config ?? null).catch(() => null) : null;
  const categories = triageCfg ? [...(triageCfg.categories ?? []), ...(triageCfg.custom_categories ?? [])] : [];
  const lastTriaged = [...d.messages].reverse().find((m) => m.direction === "in" && m.metadata.triage)?.id;
  const who = c.contact_name ?? c.contact_email ?? d.messages.find((m) => m.metadata.from)?.metadata.from ?? "Website visitor";
  return (
    <div className="grid gap-6 lg:grid-cols-[1fr_280px]">
      <div className="space-y-4">
        <Link href="/conversations" className="text-sm text-muted hover:text-ink">← Conversations</Link>
        <header>
          <h1 className="font-display text-2xl font-bold tracking-tight">{c.subject ?? (c.channel === "voice" ? "Phone call" : "Website chat")}</h1>
          <p className="text-muted">{who} · {{ email: "Email", whatsapp: "WhatsApp", web_chat: "Website chat", voice: "Phone call" }[c.channel] ?? c.channel}{c.metadata.test ? " · test chat" : ""}</p>
        </header>
        {d.messages.some((m) => m.metadata.triage?.suspicious) && (
          <div role="alert" className="rounded-2xl border-2 border-danger bg-danger/5 px-4 py-3 text-sm">
            <p className="font-semibold text-danger">⚠ This conversation may be fraud. Don&apos;t pay or share codes before checking by phone.</p>
            <ul className="mt-1 list-disc pl-5 text-ink-soft">{[...new Set(d.messages.flatMap((m) => m.metadata.triage?.risk ?? []))].map((r) => <li key={r}>{r}</li>)}</ul>
          </div>
        )}
        {c.channel === "voice" && (
          <div className="space-y-3 rounded-2xl border-2 border-line bg-card p-4">
            <div className="flex flex-wrap items-center gap-2">
              <span className="font-semibold">Call</span>
              {c.metadata.duration_seconds != null && <span className="text-sm text-muted">{Math.floor(c.metadata.duration_seconds / 60)}:{String(c.metadata.duration_seconds % 60).padStart(2, "0")} min</span>}
              {c.metadata.call && <Badge tone={OUTCOME[c.metadata.call.outcome]?.tone ?? "neutral"}>{OUTCOME[c.metadata.call.outcome]?.label ?? c.metadata.call.outcome}</Badge>}
              {c.metadata.call?.follow_up && <Badge tone="warning">Follow up{c.metadata.call.follow_up_reason ? `: ${c.metadata.call.follow_up_reason}` : ""}</Badge>}
              {!c.metadata.ended_at && <Badge>in progress or not ended yet</Badge>}
            </div>
            {c.metadata.call?.summary && <p className="text-sm">{c.metadata.call.summary}</p>}
            {c.metadata.recording
              ? <>
                  <audio controls preload="none" src={`/api/recording/${c.id}`} className="w-full"><track kind="captions" /></audio>
                  {canConfigure && <DeleteRecordingButton conversationId={c.id} />}
                </>
              : c.metadata.recording_deleted
                ? <p className="text-xs text-muted">Recording deleted {c.metadata.recording_deleted.reason === "retention" ? "after the retention period" : "on request"} ({formatDateTime(c.metadata.recording_deleted.at)}).</p>
                : c.metadata.ended_at && <p className="text-xs text-muted">No recording was kept for this call.</p>}
          </div>
        )}
        <ol className="space-y-3">
          {d.messages.map((m) => {
            const mine = m.direction === "out";
            return (
              <li key={m.id} className={cn("flex flex-col", mine ? "items-end" : "items-start")}>
                <div className={cn("max-w-[85%] rounded-2xl px-4 py-3 text-sm whitespace-pre-wrap",
                  mine ? "rounded-br-md bg-ink text-paper" : "rounded-bl-md border border-line bg-card")}>
                  {m.body || (m.metadata.body_deleted_at
                    ? <span className="italic text-muted">The email text was removed after the retention period{m.metadata.triage?.summary ? `. Summary: ${m.metadata.triage.summary}` : "."}</span>
                    : null)}
                  {m.metadata.attachments?.length ? (
                    <ul className="mt-2 space-y-1 border-t border-line pt-2 text-xs">{m.metadata.attachments.map((a) => (
                      <li key={a.filename}>📎 {a.filename} <span className="text-muted">({Math.max(1, Math.round(a.size / 1024))} KB{a.text ? ", read by Agentry" : ""})</span>
                        {a.text && <details className="mt-1"><summary className="cursor-pointer text-muted">What it says</summary>
                          <pre className="mt-1 max-h-48 overflow-auto font-sans whitespace-pre-wrap">{a.text.slice(0, 1500)}</pre></details>}</li>
                    ))}</ul>
                  ) : null}
                </div>
                <div className="mt-1 flex flex-wrap items-center gap-2 text-xs text-muted">
                  <span>{mine ? (m.author === "human" ? sender(m.metadata.sent_by) : m.metadata.sent_by?.name ?? "Agent") : who} · {formatDateTime(m.created_at)}</span>
                  {m.metadata.triage && (
                    <>
                      {m.id === lastTriaged && categories.length
                        ? <CategoryPicker conversationId={c.id} current={m.metadata.triage.category} categories={categories} />
                        : <Badge tone={categoryTone[m.metadata.triage.category] ?? "neutral"}>{m.metadata.triage.category}</Badge>}
                      {m.metadata.triage.urgent && <Badge tone="danger">Urgent{m.metadata.triage.urgent_reason ? `: ${m.metadata.triage.urgent_reason}` : ""}</Badge>}
                      <span>sorted by {m.metadata.triage.source === "rules" ? "rules" : m.metadata.triage.model ?? m.metadata.triage.source}</span>
                    </>
                  )}
                  {m.metadata.delivery && m.metadata.delivery !== "recorded" && (
                    <Badge tone={m.metadata.delivery === "failed" ? "danger" : "success"} title={m.metadata.delivery_error ?? undefined}>
                      {m.metadata.delivery === "failed" ? `not delivered: ${m.metadata.delivery_error ?? ""}` : m.metadata.delivery}
                    </Badge>
                  )}
                  {m.metadata.tools?.map((t, i) => <span key={i} className="rounded-full bg-lime-soft px-2 py-0.5 text-ink">{TOOL_LABELS[t.tool] ?? t.tool}</span>)}
                </div>
                {m.metadata.booking && (
                  <div className="mt-2 rounded-xl border-2 border-ink bg-lime px-3 py-2 text-sm text-lime-ink">
                    ✓ Booked {m.metadata.booking.service}: {m.metadata.booking.when} with {m.metadata.booking.staff}
                  </div>
                )}
              </li>
            );
          })}
        </ol>
        {canAct && !c.metadata.test && c.channel !== "voice" && (c.channel !== "email" || hasGmail) && (
          <ConversationReply id={c.id} channel={c.channel} status={c.status} agentChannel={c.channel !== "email"} />
        )}
        {canAct && c.channel === "email" && !hasGmail && (
          <p className="text-sm text-muted">Connect Gmail to reply to emails from here. Until then, reply from your own mailbox.</p>
        )}
      </div>
      <aside className="space-y-4">
        <Card className="p-5">
          <h2 className="text-sm font-semibold text-muted">Contact</h2>
          <p className="mt-1 font-medium">{who}</p>
          {c.contact_phone && <p className="text-sm text-muted">{c.contact_phone}</p>}
          {c.metadata.labels && <div className="mt-3 flex flex-wrap gap-1">{[...new Set(c.metadata.labels)].map((l) => <Badge key={l}>{l}</Badge>)}</div>}
        </Card>
        {d.bookings.length > 0 && (
          <Card className="p-5">
            <h2 className="text-sm font-semibold text-muted">Bookings</h2>
            {d.bookings.map((b) => <p key={b.starts_at} className="mt-1 text-sm">{b.service} · {formatDateTime(b.starts_at)} · {b.staff}</p>)}
          </Card>
        )}
        {d.approvals.length > 0 && (
          <Card className="p-5">
            <h2 className="text-sm font-semibold text-muted">Decisions</h2>
            {d.approvals.map((a) => (
              <p key={a.id} className="mt-1 text-sm">{approvalKinds[a.kind] ?? a.kind}: <span className={a.status === "pending" ? "font-semibold text-warning" : "text-muted"}>{a.status}</span></p>
            ))}
            {d.approvals.some((a) => a.status === "pending") && <Link href="/needs-you" className="mt-2 inline-block text-sm underline">Review in Needs you →</Link>}
          </Card>
        )}
      </aside>
    </div>
  );
}

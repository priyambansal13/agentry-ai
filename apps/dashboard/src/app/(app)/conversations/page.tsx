import { Badge, Card, cn } from "@agentry/ui";
import { Mail, MessageCircle, Phone, Smartphone } from "lucide-react";
import Link from "next/link";
import { redirect } from "next/navigation";
import { automationNames, categoryTone, timeAgo } from "@/lib/format";
import { api, ApiError, getActiveOrg, requirePage } from "@/lib/session";

export const metadata = { title: "Conversations" };

type Row = {
  id: string; channel: string; automation_key: string | null; subject: string | null; status: string; last_message_at: string;
  contact_name: string | null; contact_email: string | null; preview: string | null; call_summary: string | null; message_count: number;
  triage: { category: string; urgent?: boolean; summary?: string } | null; labels: string[] | null;
};

const FILTERS = [
  { label: "All", q: "" },
  { label: "Website chat", q: "channel=web_chat" },
  { label: "Email", q: "channel=email" },
  { label: "WhatsApp", q: "channel=whatsapp" },
  { label: "Calls", q: "channel=voice" },
  { label: "Leads", q: "category=Lead" },
  { label: "Clients", q: "category=Client" },
  { label: "Invoices", q: "category=Invoice/Payment" },
];

/** The model's one-line summary when it adds something; otherwise the start of the message itself. */
function summaryOrPreview(c: { subject: string | null; preview: string | null; call_summary?: string | null; triage: { summary?: string } | null }) {
  if (c.call_summary) return c.call_summary;  // calls: the after-call summary
  const s = c.triage?.summary?.trim();
  return s && s !== c.subject?.trim() ? s : c.preview;
}

export default async function ConversationsPage({ searchParams }: { searchParams: Promise<Record<string, string>> }) {
  const sp = await searchParams;
  const active = await getActiveOrg();
  await requirePage("conversations");
  if (!active) redirect("/home");
  const q = new URLSearchParams(Object.entries(sp).filter(([k]) => k === "channel" || k === "category")).toString();
  let data: { items: Row[] };
  try {
    data = await api(`/org/conversations?limit=100${q ? `&${q}` : ""}`, { orgId: active.id });
  } catch (e) {
    if (e instanceof ApiError && e.status === 403) redirect("/home");
    throw e;
  }
  return (
    <div className="space-y-6">
      <header>
        <h1 className="font-display text-3xl font-bold tracking-tight">Conversations</h1>
        <p className="mt-1 text-muted">Every email and chat your agents handled, with what they decided.</p>
      </header>
      <nav className="flex flex-wrap gap-2" aria-label="Filter">
        {FILTERS.map((f) => (
          <Link key={f.label} href={f.q ? `/conversations?${f.q}` : "/conversations"}
            className={cn("rounded-full border-2 px-4 py-1.5 text-sm font-medium", q === f.q ? "border-ink bg-ink text-paper" : "border-line bg-card hover:border-ink")}>
            {f.label}
          </Link>
        ))}
      </nav>
      <Card className="divide-y divide-line">
        {data.items.length === 0 && <p className="p-8 text-center text-muted">No conversations yet.</p>}
        {data.items.map((c) => {
          const Icon = c.channel === "email" ? Mail : c.channel === "whatsapp" ? Smartphone : c.channel === "voice" ? Phone : MessageCircle;
          return (
            <Link key={c.id} href={`/conversations/${c.id}`} className="flex items-start gap-4 px-5 py-4 transition-colors hover:bg-paper">
              <Icon className="mt-1 h-4 w-4 shrink-0 text-muted" aria-label={c.channel} />
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="truncate font-medium">{c.contact_name ?? c.contact_email ?? "Website visitor"}</span>
                  {c.triage?.urgent && c.triage.category !== "Urgent" && <Badge tone="danger">Urgent</Badge>}
                  {c.triage && <Badge tone={categoryTone[c.triage.category] ?? "neutral"}>{c.triage.category}</Badge>}
                  {c.status === "handed_off" && <Badge tone="warning">Needs a person</Badge>}
                </div>
                <div className="truncate text-sm">{c.subject ?? automationNames[c.automation_key ?? ""] ?? ""}</div>
                <div className="truncate text-sm text-muted">{summaryOrPreview(c)}</div>
              </div>
              <span className="shrink-0 text-xs text-muted">{timeAgo(c.last_message_at)}</span>
            </Link>
          );
        })}
      </Card>
    </div>
  );
}

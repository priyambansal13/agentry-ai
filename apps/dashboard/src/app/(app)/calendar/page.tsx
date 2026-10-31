import { Badge, Card } from "@agentry/ui";
import Link from "next/link";
import { AddToWaitlist, BookingActions, RemoveFromWaitlist } from "@/components/calendar";
import { BOOKING_STATUS } from "@/lib/format";
import { api, requirePage } from "@/lib/session";

export const metadata = { title: "Calendar" };

type Item = { id: string; starts_at: string; day: string; time: string; status: string; source: string; service: string; staff: string;
              contact: string | null; phone: string | null; email: string | null; conversation_id: string | null; awaiting: string | null;
              cancel_reason: string | null; concierge: Record<string, string>; lead_id: string | null; brief: { body: string } | null };
type Wait = { id: string; status: string; notes: string | null; service: string; contact: string; phone: string | null; email: string | null;
              offered: { starts_at: string } | null };
type Data = { start: string; days: number; timezone: string; items: Item[]; waitlist: Wait[]; services: { key: string; name: string }[];
              concierge: string | null; can_act: boolean };

const AWAITING: Record<string, string> = { confirm: "reminder sent, waiting for 1 or 2", pick_slot: "choosing a new time", rebook: "offered to rebook" };

function shift(day: string, n: number) {
  const d = new Date(`${day}T00:00:00Z`);
  d.setUTCDate(d.getUTCDate() + n);
  return d.toISOString().slice(0, 10);
}

export default async function CalendarPage({ searchParams }: { searchParams: Promise<{ start?: string }> }) {
  const active = await requirePage("calendar");
  const { start } = await searchParams;
  const d = await api<Data>(`/org/calendar?days=7${start && /^\d{4}-\d{2}-\d{2}$/.test(start) ? `&start=${start}` : ""}`, { orgId: active.id });
  const now = Date.now();
  const byDay = new Map<string, Item[]>();
  for (let i = 0; i < d.days; i++) byDay.set(shift(d.start, i), []);
  for (const i of d.items) byDay.get(i.day)?.push(i);
  const label = (day: string) => new Date(`${day}T12:00:00Z`).toLocaleDateString("en-IN", { weekday: "long", day: "numeric", month: "long", timeZone: "UTC" });
  const live = d.items.filter((i) => i.status !== "cancelled");
  return (
    <div className="space-y-6">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="font-display text-3xl font-bold tracking-tight">Calendar</h1>
          <p className="mt-1 text-muted">
            {live.length} appointment{live.length === 1 ? "" : "s"} this week · {live.filter((i) => i.status === "confirmed").length} confirmed
            {d.concierge ? ` · the concierge ${d.concierge === "live" ? "reminds and reschedules on its own" : d.concierge === "approval_mode" ? "asks you before messaging" : "is paused"}` : ""}
          </p>
        </div>
        <nav className="flex gap-2 text-sm" aria-label="Week">
          <Link href={`/calendar?start=${shift(d.start, -7)}`} className="rounded-xl border-2 border-line px-3 py-2 font-semibold hover:border-ink">← Earlier</Link>
          <Link href="/calendar" className="rounded-xl border-2 border-line px-3 py-2 font-semibold hover:border-ink">Today</Link>
          <Link href={`/calendar?start=${shift(d.start, 7)}`} className="rounded-xl border-2 border-line px-3 py-2 font-semibold hover:border-ink">Later →</Link>
        </nav>
      </header>
      <div className="grid gap-6 lg:grid-cols-[1fr_20rem]">
        <div className="min-w-0 space-y-5">
          {[...byDay.entries()].map(([day, items]) => (
            <section key={day} className="space-y-2">
              <h2 className="font-semibold">{label(day)}</h2>
              {items.length === 0 ? <p className="text-sm text-muted">Nothing booked.</p> : items.map((i) => (
                <Card key={i.id} className={`flex flex-wrap items-start justify-between gap-3 p-4 ${i.status === "cancelled" ? "opacity-60" : ""}`}>
                  <div className="min-w-0">
                    <div className="flex flex-wrap items-center gap-2 text-sm">
                      <span className="font-semibold tabular-nums">{i.time}</span>
                      <span className="font-semibold">{i.contact ?? "Customer"}</span>
                      <Badge tone={BOOKING_STATUS[i.status]?.tone ?? "neutral"}>{BOOKING_STATUS[i.status]?.label ?? i.status}</Badge>
                    </div>
                    <p className="mt-1 text-sm text-ink-soft">{i.service} with {i.staff} · booked via {i.source.replace(/_/g, " ")}</p>
                    {(i.phone || i.email) && <p className="text-xs text-muted">{[i.phone, i.email].filter(Boolean).join(" · ")}</p>}
                    {i.awaiting && AWAITING[i.awaiting] && <p className="mt-1 text-xs text-muted">Concierge: {AWAITING[i.awaiting]}</p>}
                    {i.cancel_reason && <p className="mt-1 text-xs text-muted">{i.cancel_reason}</p>}
                    <div className="flex flex-wrap gap-3">
                      {i.conversation_id && <Link href={`/conversations/${i.conversation_id}`} className="text-xs font-semibold underline">Conversation</Link>}
                      {i.lead_id && <Link href={`/leads/${i.lead_id}`} className="text-xs font-semibold underline">Lead</Link>}
                    </div>
                    {i.brief && (
                      <details className="mt-2 rounded-xl bg-paper p-3 text-sm">
                        <summary className="cursor-pointer font-semibold">Meeting brief</summary>
                        <p className="mt-2 whitespace-pre-line text-ink-soft">{i.brief.body}</p>
                      </details>
                    )}
                  </div>
                  {d.can_act && <BookingActions id={i.id} status={i.status} past={new Date(i.starts_at).getTime() < now} />}
                </Card>
              ))}
            </section>
          ))}
        </div>
        <aside className="space-y-4">
          <Card className="space-y-3 p-5">
            <h2 className="font-display text-lg font-bold">Waitlist</h2>
            <p className="text-sm text-muted">When an appointment is cancelled, the first three people waiting for that service are offered the slot. The first to reply yes gets it.</p>
            {d.waitlist.length === 0 ? <p className="text-sm text-muted">Nobody waiting.</p> : (
              <ul className="divide-y divide-line">
                {d.waitlist.map((w) => (
                  <li key={w.id} className="flex items-start justify-between gap-2 py-2 text-sm">
                    <div className="min-w-0">
                      <p className="font-semibold">{w.contact}</p>
                      <p className="text-muted">{w.service}{w.notes ? ` · ${w.notes}` : ""}</p>
                      {w.status === "offered" && w.offered && (
                        <p className="text-xs text-muted">Offered {new Date(w.offered.starts_at).toLocaleString("en-IN", { timeZone: d.timezone, weekday: "short", hour: "numeric", minute: "2-digit" })}</p>
                      )}
                    </div>
                    {d.can_act && <RemoveFromWaitlist id={w.id} />}
                  </li>
                ))}
              </ul>
            )}
          </Card>
          {d.can_act && (
            <Card className="p-5">
              <h2 className="mb-3 font-display text-lg font-bold">Add someone</h2>
              <AddToWaitlist services={d.services} />
            </Card>
          )}
        </aside>
      </div>
    </div>
  );
}

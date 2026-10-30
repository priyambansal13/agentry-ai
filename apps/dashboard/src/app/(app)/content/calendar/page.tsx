import { Badge, Card } from "@agentry/ui";
import Link from "next/link";
import { MovePost, ScheduleAll } from "@/components/content";
import { PLATFORM } from "@/lib/format";
import { api, requirePage } from "@/lib/session";

export const metadata = { title: "Content calendar" };

type Item = { id: string; platform: keyof typeof PLATFORM; body: string; scheduled_at: string; published_at: string | null; publish_ref: string | null;
              publish_error: string | null; has_image: boolean; source_title: string; hook: string };

export default async function ContentCalendarPage() {
  const active = await requirePage("content");
  const d = await api<{ timezone: string; items: Item[]; approved_unscheduled: number; can_edit: boolean }>("/org/content/calendar?days=60", { orgId: active.id });
  const days = new Map<string, Item[]>();
  for (const i of d.items) {
    const key = new Date(i.scheduled_at).toLocaleDateString("en-IN", { timeZone: d.timezone, weekday: "long", day: "numeric", month: "long" });
    days.set(key, [...(days.get(key) ?? []), i]);
  }
  return (
    <div className="space-y-6">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <Link href="/content" className="text-sm text-muted hover:text-ink">← Content</Link>
          <h1 className="mt-1 font-display text-3xl font-bold tracking-tight">Calendar</h1>
          <p className="mt-1 text-muted">LinkedIn on weekdays at 9:30, Instagram at 12:30, X at 10:00 and 16:00 ({d.timezone}). Never two posts from the same moment on one day.</p>
        </div>
        {d.can_edit && <ScheduleAll count={d.approved_unscheduled} />}
      </header>
      {days.size === 0 ? <p className="text-muted">Nothing scheduled. Approve posts on a recording, then schedule them.</p> : [...days.entries()].map(([day, items]) => (
        <section key={day} className="space-y-2">
          <h2 className="font-semibold">{day}</h2>
          {items.map((i) => (
            <Card key={i.id} className="flex flex-wrap items-start gap-4 p-4">
              {i.has_image && (
                // eslint-disable-next-line @next/next/no-img-element
                <img src={`/api/content-image/${i.id}`} alt="" className="h-20 w-20 shrink-0 rounded-lg border border-line object-cover" loading="lazy" />
              )}
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-center gap-2 text-sm">
                  <span className="font-semibold tabular-nums">{new Date(i.scheduled_at).toLocaleTimeString("en-IN", { timeZone: d.timezone, hour: "numeric", minute: "2-digit" })}</span>
                  <Badge>{PLATFORM[i.platform]}</Badge>
                  {i.published_at && <Badge tone="success">Published{i.publish_ref?.startsWith("test-mode") ? " (test mode)" : ""}</Badge>}
                  {i.publish_error && <Badge tone="danger">{i.publish_error}</Badge>}
                  <span className="text-xs text-muted">from {i.source_title}</span>
                </div>
                <p className="mt-1 line-clamp-2 text-sm text-ink-soft">{i.body}</p>
              </div>
              {d.can_edit && !i.published_at && <MovePost id={i.id} at={i.scheduled_at} />}
            </Card>
          ))}
        </section>
      ))}
    </div>
  );
}

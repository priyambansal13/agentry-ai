import { Badge, Card } from "@agentry/ui";
import { AddWatcher, WatcherActions } from "@/components/watch";
import { timeAgo } from "@/lib/format";
import { api, requirePage } from "@/lib/session";

export const metadata = { title: "Competitor & price watch" };

type W = { id: string; kind: string; name: string; url: string; every_minutes: number; status: string; error: string | null;
           last_checked_at: string | null; last_changed_at: string | null; value: { title?: string; price?: number | null; currency?: string | null; in_stock?: boolean } | null };
type Data = { items: W[]; changes: { watcher_id: string; at: string; summary: string | null }[]; max_pages: number; can_edit: boolean };

export default async function WatchPage() {
  const active = await requirePage("watch");
  const d = await api<Data>("/org/watchers", { orgId: active.id });
  const name = Object.fromEntries(d.items.map((w) => [w.id, w.name]));
  return (
    <div className="space-y-6">
      <header>
        <h1 className="font-display text-3xl font-bold tracking-tight">Competitor &amp; price watch</h1>
        <p className="mt-1 text-muted">Pages are checked every few hours. You only hear about real changes (new offers, prices past your threshold, stock), in plain words.</p>
      </header>
      {d.can_edit && <Card className="p-5"><AddWatcher /><p className="mt-2 text-xs text-muted">{d.items.length} of {d.max_pages} pages in your plan.</p></Card>}
      <div className="grid gap-6 lg:grid-cols-[1fr_22rem]">
        <section className="space-y-3">
          {d.items.length === 0 && <p className="text-muted">Nothing watched yet. Add a competitor&apos;s offers page or a product page.</p>}
          {d.items.map((w) => (
            <Card key={w.id} className="p-5">
              <div className="flex flex-wrap items-center gap-2">
                <h2 className="font-semibold">{w.name}</h2>
                <Badge>{w.kind === "price" ? "price" : "page"}</Badge>
                {w.status === "paused" && <Badge>paused</Badge>}
                {w.status === "error" && <Badge tone="danger">can&apos;t read it</Badge>}
              </div>
              <a href={w.url} target="_blank" rel="noreferrer" className="block truncate text-xs text-muted underline">{w.url}</a>
              {w.kind === "price" && w.value && (
                <p className="mt-2 text-sm">{w.value.price != null ? `${w.value.currency ?? ""} ${w.value.price.toLocaleString("en-IN")}` : "price not found"} ·{" "}
                  {w.value.in_stock === false ? <span className="text-danger">out of stock</span> : "in stock"}</p>
              )}
              <p className="mt-1 text-xs text-muted">
                {w.last_checked_at ? `Checked ${timeAgo(w.last_checked_at)}` : "Not checked yet"} · every {Math.round(w.every_minutes / 60)} h
                {w.last_changed_at ? ` · last change ${timeAgo(w.last_changed_at)}` : ""}
              </p>
              {w.error && <p className="mt-1 text-sm text-danger">{w.error}</p>}
              {d.can_edit && <div className="mt-3"><WatcherActions id={w.id} status={w.status} /></div>}
            </Card>
          ))}
        </section>
        <aside>
          <Card className="space-y-3 p-5">
            <h2 className="font-display text-lg font-bold">Recent changes</h2>
            {d.changes.length === 0 ? <p className="text-sm text-muted">None yet.</p> : (
              <ul className="space-y-3 text-sm">
                {d.changes.map((c, i) => (
                  <li key={i}><p className="font-semibold">{name[c.watcher_id] ?? "Removed page"}</p><p className="text-ink-soft">{c.summary}</p>
                    <p className="text-xs text-muted">{timeAgo(c.at)}</p></li>
                ))}
              </ul>
            )}
          </Card>
        </aside>
      </div>
    </div>
  );
}

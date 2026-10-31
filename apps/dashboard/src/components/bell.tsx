"use client";

import { Bell as BellIcon } from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";
import { getInbox, type InboxItem, markInboxRead } from "@/app/(app)/actions";
import { timeAgo } from "@/lib/format";

/** The in-app inbox: every notification this person got (Notification Center), newest first. Checks every minute. */
export function Bell() {
  const [open, setOpen] = useState(false);
  const [items, setItems] = useState<InboxItem[]>([]);
  const [unread, setUnread] = useState(0);
  const panel = useRef<HTMLDivElement>(null);

  const load = useCallback(async () => {
    const r = await getInbox();
    if (r.ok) { setItems(r.data.items); setUnread(r.data.unread); }
  }, []);

  useEffect(() => {
    load();
    const t = setInterval(load, 60_000);
    return () => clearInterval(t);
  }, [load]);

  useEffect(() => {
    if (!open) return;
    const close = (e: MouseEvent) => { if (panel.current && !panel.current.contains(e.target as Node)) setOpen(false); };
    const esc = (e: KeyboardEvent) => { if (e.key === "Escape") setOpen(false); };
    document.addEventListener("mousedown", close);
    document.addEventListener("keydown", esc);
    return () => { document.removeEventListener("mousedown", close); document.removeEventListener("keydown", esc); };
  }, [open]);

  async function readAll() {
    await markInboxRead();
    setUnread(0);
    setItems((xs) => xs.map((x) => ({ ...x, read_at: x.read_at ?? new Date().toISOString() })));
  }

  return (
    <div className="relative" ref={panel}>
      <button type="button" onClick={() => { setOpen((o) => !o); if (!open) load(); }} aria-expanded={open} aria-haspopup="dialog"
        aria-label={unread ? `Notifications, ${unread} unread` : "Notifications"}
        className="relative grid h-9 w-9 place-items-center rounded-full border-2 border-line hover:border-ink">
        <BellIcon className="h-4 w-4" aria-hidden="true" />
        {unread > 0 && <span className="absolute -top-1 -right-1 min-w-5 rounded-full border-2 border-card bg-ink px-1 text-center text-[11px] font-semibold leading-4 text-paper">{unread > 99 ? "99+" : unread}</span>}
      </button>
      {open && (
        <div role="dialog" aria-label="Notifications" className="fixed inset-x-4 top-16 z-50 rounded-2xl border-2 border-ink bg-card shadow-[4px_4px_0_0_var(--ink)] lg:absolute lg:inset-x-auto lg:top-auto lg:left-0 lg:mt-2 lg:w-[22rem]">
          <div className="flex items-center justify-between border-b border-line px-4 py-3">
            <span className="font-semibold">Notifications</span>
            {unread > 0 && <button type="button" onClick={readAll} className="text-xs text-muted underline hover:text-ink">Mark all read</button>}
          </div>
          <ul className="max-h-96 divide-y divide-line overflow-y-auto">
            {items.length === 0 && <li className="px-4 py-6 text-center text-sm text-muted">Nothing yet.</li>}
            {items.map((n) => {
              const body = (
                <span className="block">
                  <span className={`block text-sm ${n.read_at ? "text-ink-soft" : "font-semibold"}`}>{n.critical ? "⚠ " : ""}{n.title}</span>
                  {n.body && <span className="mt-0.5 block line-clamp-2 text-xs text-muted">{n.body}</span>}
                  <span className="mt-1 block text-[11px] text-muted">{timeAgo(n.created_at)}{n.status === "held" ? " · held for quiet hours" : n.status === "digest" ? " · in your next digest" : ""}</span>
                </span>
              );
              return (
                <li key={n.id} className={n.read_at ? "" : "bg-lime-soft/40"}>
                  {n.link ? <Link href={n.link} onClick={() => { markInboxRead([n.id]); setOpen(false); }} className="block px-4 py-3 hover:bg-paper">{body}</Link>
                    : <div className="px-4 py-3">{body}</div>}
                </li>
              );
            })}
          </ul>
          <div className="border-t border-line px-4 py-2.5 text-right">
            <Link href="/settings/notifications" onClick={() => setOpen(false)} className="text-xs font-medium underline">Notification rules</Link>
          </div>
        </div>
      )}
    </div>
  );
}

"use client";

import { useRouter } from "next/navigation";
import { useState, useTransition } from "react";
import { recategorise } from "@/app/(app)/actions";

/** "Wrong label?" (#8): move the email to the right category; Agentry remembers it for this sender. */
export function CategoryPicker({ conversationId, current, categories }: { conversationId: string; current: string; categories: string[] }) {
  const router = useRouter();
  const [pending, start] = useTransition();
  const [msg, setMsg] = useState<string | null>(null);
  return (
    <span className="inline-flex items-center gap-2">
      <select aria-label="Category" value={current} disabled={pending} className="h-7 rounded-lg border border-line bg-card px-1.5 text-xs"
        onChange={(e) => start(async () => {
          const r = await recategorise(conversationId, e.target.value);
          setMsg(r.ok ? `Moved to ${r.data.category}: future emails from this sender go there too` : r.error);
          router.refresh();
        })}>
        {[...new Set([current, ...categories])].map((c) => <option key={c}>{c}</option>)}
      </select>
      {msg && <span role="status" className="text-xs text-muted">{msg}</span>}
    </span>
  );
}

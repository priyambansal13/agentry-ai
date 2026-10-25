"use client";

import { useTransition } from "react";
import { exitClientView } from "@/app/(app)/actions";

/** Shown instead of the org switcher while Agentry staff are inside a client's portal. */
export function ExitClientView({ name }: { name: string }) {
  const [pending, start] = useTransition();
  return (
    <div className="rounded-xl border-2 border-dashed border-ink bg-lime-soft px-3 py-2">
      <p className="text-xs font-semibold uppercase tracking-wide text-muted">Agentry staff view</p>
      <p className="truncate font-semibold">{name}</p>
      <p className="text-xs text-muted">The client sees exactly these sections.</p>
      <button type="button" disabled={pending} onClick={() => start(() => exitClientView())}
        className="mt-1 text-sm font-semibold underline-offset-2 hover:underline">← Back to Agentry HQ</button>
    </div>
  );
}

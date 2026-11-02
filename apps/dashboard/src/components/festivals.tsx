"use client";

import { Button } from "@agentry/ui";
import { useRouter } from "next/navigation";
import { useState, useTransition } from "react";
import { festivalStatus, planFestival } from "@/app/(app)/actions";

/** Festival campaigns (ROADMAP-V3 B3). */
export function PlanButton({ festival, date }: { festival: string; date: string }) {
  const router = useRouter();
  const [pending, start] = useTransition();
  const [err, setErr] = useState<string | null>(null);
  return <span className="flex items-center gap-2"><Button size="sm" variant="secondary" disabled={pending}
    onClick={() => start(async () => { const r = await planFestival(festival, date); if (!r.ok) setErr(r.error); router.refresh(); })}>{pending ? "Planning…" : "Plan it"}</Button>
    {err && <span className="text-xs text-danger">{err}</span>}</span>;
}

export function PlanStatus({ id, status }: { id: string; status: string }) {
  const router = useRouter();
  const [pending, start] = useTransition();
  const set = (s: string) => start(async () => { await festivalStatus(id, s); router.refresh(); });
  return <span className="flex gap-2">{status !== "approved" && status !== "needs_attention" && <Button size="sm" disabled={pending} onClick={() => set("approved")}>Approve</Button>}
    {status === "approved" && <Button size="sm" variant="secondary" disabled={pending} onClick={() => set("done")}>Mark done</Button>}
    {status !== "skipped" && <Button size="sm" variant="ghost" disabled={pending} onClick={() => set("skipped")}>Skip</Button>}</span>;
}

"use client";

import { Button } from "@agentry/ui";
import { useRouter } from "next/navigation";
import { useState, useTransition } from "react";
import { researchLead } from "@/app/(app)/actions";

export function ResearchAgain({ id, first }: { id: string; first: boolean }) {
  const router = useRouter();
  const [pending, start] = useTransition();
  const [err, setErr] = useState<string | null>(null);
  return (
    <div className="flex flex-wrap items-center gap-3">
      <Button size="sm" variant="secondary" disabled={pending}
              onClick={() => start(async () => { const r = await researchLead(id); setErr(r.ok ? null : r.error); if (r.ok) router.refresh(); })}>
        {pending ? "Researching…" : first ? "Research now" : "Research again"}
      </Button>
      {err && <span role="status" className="text-sm text-danger">{err}</span>}
    </div>
  );
}

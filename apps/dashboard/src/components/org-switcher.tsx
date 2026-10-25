"use client";

import { cn } from "@agentry/ui";
import { Check, ChevronsUpDown } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState, useTransition } from "react";
import { authClient } from "@/lib/auth-client";
import type { OrgSummary } from "@/lib/session";

export function OrgSwitcher({ orgs, activeId }: { orgs: OrgSummary[]; activeId: string | null }) {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [pending, start] = useTransition();
  const active = orgs.find((o) => o.id === activeId);

  if (orgs.length === 0) return <div className="px-3 text-sm text-muted">No client organisations</div>;

  function choose(id: string) {
    setOpen(false);
    start(async () => {
      await authClient.organization.setActive({ organizationId: id });
      router.refresh();
    });
  }

  return (
    <div className="relative">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        disabled={orgs.length < 2 || pending}
        aria-haspopup="listbox"
        aria-expanded={open}
        className="flex w-full items-center gap-3 rounded-xl border-2 border-line bg-card px-3 py-2 text-left transition-colors hover:border-ink disabled:hover:border-line"
      >
        <span className="grid h-8 w-8 shrink-0 place-items-center rounded-lg bg-lime font-display font-bold text-lime-ink">
          {active?.name.charAt(0) ?? "?"}
        </span>
        <span className="min-w-0 flex-1">
          <span className="block truncate text-sm font-semibold">{active?.name ?? "Choose organisation"}</span>
          <span className="block text-xs text-muted">{active?.role_label}</span>
        </span>
        {orgs.length > 1 && <ChevronsUpDown className="h-4 w-4 text-muted" />}
      </button>
      {open && (
        <ul role="listbox" className="absolute z-20 mt-1 w-full overflow-hidden rounded-xl border border-line bg-card-raised p-1 shadow-card">
          {orgs.map((o) => (
            <li key={o.id}>
              <button
                type="button"
                role="option"
                aria-selected={o.id === activeId}
                onClick={() => choose(o.id)}
                className={cn("flex w-full items-center gap-2 rounded-lg px-3 py-2 text-left text-sm hover:bg-lime-soft")}
              >
                <span className="flex-1 truncate">{o.name}</span>
                <span className="text-xs text-muted">{o.role_label}</span>
                {o.id === activeId && <Check className="h-4 w-4" />}
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

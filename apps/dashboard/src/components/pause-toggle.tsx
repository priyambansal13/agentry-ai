"use client";

import { Button } from "@agentry/ui";
import { useState, useTransition } from "react";
import { setAutomationState } from "@/app/(app)/actions";

export function PauseToggle({ automationKey, status, canConfigure = false }: { automationKey: string; status: string; canConfigure?: boolean }) {
  const [pending, start] = useTransition();
  const [error, setError] = useState<string | null>(null);
  if (status === "setup") return null;
  const paused = status === "paused";
  const mode = status === "approval_mode" ? "automatic" : status === "live" ? "approval" : null;
  return (
    <div className="flex flex-wrap items-center gap-2">
      {canConfigure && mode && (
        <Button variant="secondary" size="sm" disabled={pending}
          onClick={() => {
            if (mode === "automatic" && !confirm("Switch to automatic? The agent will send its messages without waiting for your approval.")) return;
            start(async () => { const r = await setAutomationState(automationKey, mode); setError(r.ok ? null : r.error); });
          }}>
          {mode === "automatic" ? "Switch to automatic" : "Back to approval mode"}
        </Button>
      )}
      <Button variant={paused ? "primary" : "secondary"} size="sm" disabled={pending}
        onClick={() => start(async () => {
          const r = await setAutomationState(automationKey, paused ? "resume" : "pause");
          setError(r.ok ? null : r.error);
        })}>
        {pending ? "…" : paused ? "Resume" : "Pause"}
      </Button>
      {error && <span className="text-xs text-danger">{error}</span>}
    </div>
  );
}

"use client";

import { Button, Input, Label } from "@agentry/ui";
import { useState, useTransition } from "react";
import { deleteRecording, saveVoiceSettings } from "@/app/(app)/actions";

export function RetentionForm({ days }: { days: number }) {
  const [value, setValue] = useState(String(days));
  const [pending, start] = useTransition();
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  return (
    <form className="flex flex-wrap items-end gap-3" onSubmit={(e) => {
      e.preventDefault();
      start(async () => {
        const r = await saveVoiceSettings(Number(value));
        setMsg(r.ok ? { ok: true, text: "Saved" } : { ok: false, text: r.error });
      });
    }}>
      <div>
        <Label htmlFor="retention">Keep call recordings for (days)</Label>
        <Input id="retention" type="number" min={7} max={730} value={value} onChange={(e) => setValue(e.target.value)} className="w-32" />
      </div>
      <Button type="submit" variant="secondary" disabled={pending}>Save</Button>
      {msg && <p role={msg.ok ? "status" : "alert"} className={msg.ok ? "text-sm text-success" : "text-sm text-danger"}>{msg.text}</p>}
    </form>
  );
}

export function DeleteRecordingButton({ conversationId }: { conversationId: string }) {
  const [pending, start] = useTransition();
  const [error, setError] = useState<string | null>(null);
  return (
    <span className="inline-flex items-center gap-2">
      <button type="button" disabled={pending} className="text-xs text-muted underline-offset-4 hover:text-danger hover:underline"
        onClick={() => {
          if (!confirm("Delete this call recording for good? The transcript and summary stay.")) return;
          start(async () => { const r = await deleteRecording(conversationId); if (!r.ok) setError(r.error); });
        }}>Delete recording</button>
      {error && <span role="alert" className="text-xs text-danger">{error}</span>}
    </span>
  );
}

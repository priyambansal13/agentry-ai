"use client";

import { Button, Input, Label, Textarea } from "@agentry/ui";
import { useRouter } from "next/navigation";
import { useState, useTransition } from "react";
import { deleteReplyTemplate, saveReplyTemplate, updateReplyTemplate } from "@/app/(app)/actions";
import type { SavedReply } from "@/components/approval-card";

export function SavedReplyEditor({ t }: { t?: SavedReply }) {
  const router = useRouter();
  const [title, setTitle] = useState(t?.title ?? "");
  const [body, setBody] = useState(t?.body ?? "");
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [pending, start] = useTransition();
  const id = t?.id ?? "new";
  return (
    <form className="space-y-2" onSubmit={(e) => {
      e.preventDefault();
      start(async () => {
        const r = t ? await updateReplyTemplate(t.id, title, body) : await saveReplyTemplate(title, body);
        setMsg(r.ok ? { ok: true, text: "Saved" } : { ok: false, text: r.error });
        if (r.ok && !t) { setTitle(""); setBody(""); }
        router.refresh();
      });
    }}>
      <div className="space-y-1"><Label htmlFor={`t-${id}`}>Title</Label>
        <Input id={`t-${id}`} required minLength={2} maxLength={80} value={title} onChange={(e) => setTitle(e.target.value)} placeholder="e.g. Audit fees" /></div>
      <div className="space-y-1"><Label htmlFor={`b-${id}`}>Reply</Label>
        <Textarea id={`b-${id}`} required rows={4} value={body} onChange={(e) => setBody(e.target.value)} /></div>
      <div className="flex items-center gap-3">
        <Button type="submit" size="sm" disabled={pending}>{t ? "Save changes" : "Add"}</Button>
        {t && <Button type="button" size="sm" variant="secondary" disabled={pending} onClick={() => confirm(`Delete "${t.title}"?`) && start(async () => {
          const r = await deleteReplyTemplate(t.id);
          if (!r.ok) setMsg({ ok: false, text: r.error });
          router.refresh();
        })}>Delete</Button>}
        {msg && <span role={msg.ok ? "status" : "alert"} className={`text-sm ${msg.ok ? "text-success" : "text-danger"}`}>{msg.text}</span>}
      </div>
    </form>
  );
}

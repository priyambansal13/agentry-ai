"use client";

import { Button, Card } from "@agentry/ui";
import { useRouter } from "next/navigation";
import { useState, useTransition } from "react";
import { relearnStyle } from "@/app/(app)/actions";

/** How drafts sound (#1): the style guide learned from the business's sent emails, and a button to learn it again. */
export function WritingStyleCard({ style, canConfigure }: { style: { guide: string; learned_at: string; samples: number } | null; canConfigure: boolean }) {
  const router = useRouter();
  const [pending, start] = useTransition();
  const [msg, setMsg] = useState<string | null>(null);
  return (
    <Card className="p-5">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="font-semibold">Your writing style</h2>
        {canConfigure && <Button size="sm" variant="secondary" disabled={pending} onClick={() => start(async () => {
          const r = await relearnStyle();
          setMsg(r.ok ? (r.data.learned ? `Learned from ${r.data.samples} sent emails` : `Not enough sent emails yet (${r.data.samples})`) : r.error);
          router.refresh();
        })}>{pending ? "Reading your sent emails…" : style ? "Learn again" : "Learn from my sent emails"}</Button>}
      </div>
      {style
        ? <><pre className="mt-2 font-sans text-sm whitespace-pre-wrap text-ink-soft">{style.guide}</pre>
            <p className="mt-2 text-xs text-muted">Learned from {style.samples} of your sent emails on {new Date(style.learned_at).toLocaleDateString("en-IN")}. Drafts follow it. Only this summary is kept, not your emails.</p></>
        : <p className="mt-2 text-sm text-muted">Not learned yet. It&apos;s learned from your sent emails when Gmail is connected, so drafts sound like you.</p>}
      {msg && <p role="status" className="mt-2 text-sm">{msg}</p>}
    </Card>
  );
}

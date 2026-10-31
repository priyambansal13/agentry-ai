"use client";

import { Button, Textarea } from "@agentry/ui";
import { useRouter } from "next/navigation";
import { useState, useTransition } from "react";
import { replyToReview, syncReviews } from "@/app/(app)/actions";

type Msg = { ok: boolean; text: string } | null;
const Status = ({ msg }: { msg: Msg }) => msg && <span role="status" className={`text-sm ${msg.ok ? "text-success" : "text-danger"}`}>{msg.text}</span>;

export function CheckReviews() {
  const router = useRouter();
  const [pending, start] = useTransition();
  const [msg, setMsg] = useState<Msg>(null);
  return (
    <div className="flex items-center gap-3">
      <Button variant="secondary" disabled={pending} onClick={() => start(async () => {
        const r = await syncReviews();
        setMsg(r.ok ? { ok: true, text: r.data.new ? `${r.data.new} new review${r.data.new === 1 ? "" : "s"}` : "No new reviews" } : { ok: false, text: r.error });
        router.refresh();
      })}>{pending ? "Checking…" : "Check for new reviews"}</Button>
      <Status msg={msg} />
    </div>
  );
}

/** The drafted reply: edit it, then post it (it appears under the review) or skip. */
export function ReplyBox({ id, draft }: { id: string; draft: string }) {
  const router = useRouter();
  const [pending, start] = useTransition();
  const [body, setBody] = useState(draft);
  const [msg, setMsg] = useState<Msg>(null);
  const act = (action: "post" | "skip") => start(async () => {
    const r = await replyToReview(id, action, action === "post" ? body : undefined);
    setMsg(r.ok ? { ok: true, text: action === "post" ? "Reply posted" : "Skipped" } : { ok: false, text: r.error });
    if (r.ok) router.refresh();
  });
  return (
    <div className="mt-3 space-y-2">
      <label className="text-xs font-semibold text-muted" htmlFor={`reply-${id}`}>Drafted reply</label>
      <Textarea id={`reply-${id}`} rows={3} value={body} onChange={(e) => setBody(e.target.value)} />
      <div className="flex flex-wrap items-center gap-2">
        <Button size="sm" disabled={pending || !body.trim()} onClick={() => act("post")}>Post reply</Button>
        <Button size="sm" variant="ghost" disabled={pending} onClick={() => act("skip")}>Don&apos;t reply</Button>
        <Status msg={msg} />
      </div>
    </div>
  );
}

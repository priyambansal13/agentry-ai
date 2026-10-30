"use client";

import { useState, useTransition } from "react";
import { confirmUnsubscribe } from "./actions";

export function ConfirmUnsubscribe({ token, email }: { token: string; email: string }) {
  const [done, setDone] = useState<boolean | null>(null);
  const [pending, start] = useTransition();
  if (done) return <p role="status" className="mt-6 font-semibold">Done. {email} won&apos;t get these emails again.</p>;
  return (
    <div className="mt-6">
      <button type="button" disabled={pending} onClick={() => start(async () => setDone(await confirmUnsubscribe(token)))}
        className="inline-flex h-11 items-center rounded-xl border-2 border-ink bg-lime px-5 text-sm font-semibold text-lime-ink disabled:opacity-60">
        {pending ? "Unsubscribing…" : "Unsubscribe"}
      </button>
      {done === false && <p role="alert" className="mt-3 text-sm text-danger">That didn&apos;t work. Reply &quot;stop&quot; to the email instead and we&apos;ll remove you.</p>}
    </div>
  );
}

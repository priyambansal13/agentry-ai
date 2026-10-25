"use client";

import { Button, Label, PasswordInput } from "@agentry/ui";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";
import { authClient } from "@/lib/auth-client";

export default function ResetPasswordPage() {
  return <Suspense><ResetPassword /></Suspense>;
}

function ResetPassword() {
  const router = useRouter();
  const params = useSearchParams();
  const token = params.get("token");
  const [pw, setPw] = useState("");
  const [again, setAgain] = useState("");
  const [status, setStatus] = useState<{ busy?: boolean; error?: string }>({});

  if (!token || params.get("error")) {
    return (
      <div>
        <h1 className="font-display text-3xl font-bold tracking-tight">This link has expired</h1>
        <p className="mt-2 text-muted">Reset links work once and for 1 hour. Ask for a new one.</p>
        <Link href="/forgot-password" className="mt-6 inline-block font-medium underline">Send a new reset link</Link>
      </div>
    );
  }

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (pw !== again) return setStatus({ error: "The two passwords don't match" });
    setStatus({ busy: true });
    const { error } = await authClient.resetPassword({ newPassword: pw, token: token! });
    if (error) {
      return setStatus({ error: /token/i.test(error.message ?? "") ? "This link has expired or was already used. Ask for a new one."
                                                                   : error.message ?? "Couldn't save the password" });
    }
    router.replace("/sign-in?reset=1");
  }

  return (
    <div>
      <h1 className="font-display text-3xl font-bold tracking-tight">Choose a new password</h1>
      <p className="mt-2 text-muted">At least 10 characters. You&apos;ll be signed out on your other devices.</p>
      <form onSubmit={submit} className="mt-8 space-y-4">
        <div>
          <Label htmlFor="new-pw">New password</Label>
          <PasswordInput id="new-pw" autoComplete="new-password" required minLength={10} value={pw} onChange={(e) => setPw(e.target.value)} />
        </div>
        <div>
          <Label htmlFor="new-pw2">New password again</Label>
          <PasswordInput id="new-pw2" autoComplete="new-password" required minLength={10} value={again} onChange={(e) => setAgain(e.target.value)} />
        </div>
        <Button type="submit" size="lg" className="w-full" disabled={status.busy}>{status.busy ? "Saving…" : "Save new password"}</Button>
        {status.error && <p role="alert" className="text-sm text-danger">{status.error}</p>}
      </form>
    </div>
  );
}

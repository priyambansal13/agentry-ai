"use client";

import { Button, Input, Label } from "@agentry/ui";
import Link from "next/link";
import { Suspense, useState } from "react";
import { useSearchParams } from "next/navigation";
import { authClient } from "@/lib/auth-client";

export default function ForgotPasswordPage() {
  return <Suspense><ForgotPassword /></Suspense>;
}

function ForgotPassword() {
  const [email, setEmail] = useState(useSearchParams().get("email") ?? "");
  const [status, setStatus] = useState<{ kind: "idle" | "busy" | "sent" | "error"; message?: string }>({ kind: "idle" });

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setStatus({ kind: "busy" });
    const { error } = await authClient.requestPasswordReset({ email, redirectTo: "/reset-password" });
    // Same answer whether or not the email has an account, so nobody can use this page to check who's a customer.
    setStatus(error ? { kind: "error", message: error.message ?? "Couldn't send the email. Try again in a minute." }
                    : { kind: "sent", message: `If ${email} has an Agentry account, a reset link is on its way. It expires in 1 hour; check spam if you don't see it.` });
  }

  return (
    <div>
      <h1 className="font-display text-3xl font-bold tracking-tight">Forgot your password?</h1>
      <p className="mt-2 text-muted">Enter your email and we&apos;ll send you a link to choose a new one.</p>
      <form onSubmit={submit} className="mt-8 space-y-4">
        <div>
          <Label htmlFor="email">Work email</Label>
          <Input id="email" type="email" autoComplete="email" required value={email} onChange={(e) => setEmail(e.target.value)} />
        </div>
        <Button type="submit" size="lg" className="w-full" disabled={status.kind === "busy" || status.kind === "sent"}>
          {status.kind === "busy" ? "Sending…" : status.kind === "sent" ? "Link sent" : "Send reset link"}
        </Button>
        {status.message && (
          <p role="status" className={`text-sm ${status.kind === "error" ? "text-danger" : "text-success"}`}>{status.message}</p>
        )}
      </form>
      <p className="mt-6 text-sm text-muted"><Link href="/sign-in" className="font-medium text-ink underline">Back to sign in</Link></p>
    </div>
  );
}

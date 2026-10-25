"use client";

import { Button, Input, Label, PasswordInput } from "@agentry/ui";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";
import { authClient } from "@/lib/auth-client";

const DEMO_ACCOUNTS = [
  ["riya@sharmadigital.example", "Agency owner"],
  ["neha@smilecraft.example", "Clinic owner"],
  ["frontdesk@smilecraft.example", "Front desk"],
  ["multi@agentry.dev", "Two businesses"],
  ["admin@agentry.dev", "Agentry staff"],
] as const;

export default function SignInPage() {
  return <Suspense><SignIn /></Suspense>;
}

function SignIn() {
  const router = useRouter();
  const params = useSearchParams();
  const next = params.get("next") ?? "/home";
  const [mode, setMode] = useState<"password" | "link">("password");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [status, setStatus] = useState<{ kind: "idle" | "busy" | "sent" | "error"; message?: string }>(
    params.get("reset") ? { kind: "sent", message: "Password changed. Sign in with your new password." } : { kind: "idle" });

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setStatus({ kind: "busy" });
    if (mode === "link") {
      const { error } = await authClient.signIn.magicLink({ email, callbackURL: next });
      return setStatus(error ? { kind: "error", message: error.message } : { kind: "sent", message: `Check ${email} for your sign-in link.` });
    }
    const { error } = await authClient.signIn.email({ email, password });
    if (error) return setStatus({ kind: "error", message: error.message ?? "Wrong email or password" });
    router.push(next);
    router.refresh();
  }

  return (
    <div>
      <h1 className="font-display text-3xl font-bold tracking-tight">Welcome back</h1>
      <p className="mt-2 text-muted">Sign in to see what your agents have been doing.</p>

      <div className="mt-8 grid grid-cols-2 rounded-xl border-2 border-line p-1 text-sm" role="tablist">
        {(["password", "link"] as const).map((m) => (
          <button key={m} type="button" role="tab" aria-selected={mode === m} onClick={() => setMode(m)}
            className={`rounded-lg py-2 font-medium transition-colors ${mode === m ? "bg-ink text-paper" : "text-muted hover:text-ink"}`}>
            {m === "password" ? "Password" : "Email me a link"}
          </button>
        ))}
      </div>

      <form onSubmit={submit} className="mt-6 space-y-4">
        <div>
          <Label htmlFor="email">Work email</Label>
          <Input id="email" type="email" autoComplete="email" required value={email} onChange={(e) => setEmail(e.target.value)} />
        </div>
        {mode === "password" && (
          <div>
            <div className="flex items-baseline justify-between">
              <Label htmlFor="password">Password</Label>
              <Link href={`/forgot-password${email ? `?email=${encodeURIComponent(email)}` : ""}`} className="text-sm text-muted underline hover:text-ink">
                Forgot password?
              </Link>
            </div>
            <PasswordInput id="password" autoComplete="current-password" required value={password} onChange={(e) => setPassword(e.target.value)} />
          </div>
        )}
        <Button type="submit" size="lg" className="w-full" disabled={status.kind === "busy"}>
          {status.kind === "busy" ? "Signing in…" : mode === "link" ? "Send sign-in link" : "Sign in"}
        </Button>
        {status.message && (
          <p role="status" className={`text-sm ${status.kind === "error" ? "text-danger" : "text-success"}`}>{status.message}</p>
        )}
      </form>

      {process.env.NODE_ENV !== "production" && (
        <div className="mt-10 rounded-2xl border-2 border-dashed border-line p-4">
          <p className="font-hand text-lg text-muted">demo accounts · password agentry-demo-123</p>
          <div className="mt-2 flex flex-wrap gap-2">
            {DEMO_ACCOUNTS.map(([e, label]) => (
              <button key={e} type="button" onClick={() => { setMode("password"); setEmail(e); setPassword("agentry-demo-123"); }}
                className="rounded-full border border-line px-3 py-1 text-xs hover:border-ink">{label}</button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

"use client";

import { Button, buttonClasses, Label, PasswordInput } from "@agentry/ui";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useEffect, useRef, useState, useTransition } from "react";
import { savePassword } from "@/app/(app)/actions";
import { authClient } from "@/lib/auth-client";

export default function AcceptInvitationPage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const session = authClient.useSession();
  const [error, setError] = useState<string | null>(null);
  const [joined, setJoined] = useState(false);
  const [joining, setJoining] = useState(false);
  const started = useRef(false); // accept once, even if the effect runs twice

  async function accept() {
    const { data, error: err } = await authClient.organization.acceptInvitation({ invitationId: id });
    if (err) return setError(err.message ?? "This invitation is no longer valid.");
    await authClient.organization.setActive({ organizationId: data!.invitation.organizationId });
    return data!.invitation.organizationId;
  }

  // Arrived from the one-click link in the invitation email (/invite/[id]): join straight away, then offer a password.
  useEffect(() => {
    if (started.current || !session.data || new URLSearchParams(window.location.search).get("welcome") !== "1") return;
    started.current = true;
    setJoining(true);
    accept().then((orgId) => { setJoining(false); if (orgId) setJoined(true); });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [session.data]);

  if (session.isPending) return <p className="text-muted">Loading…</p>;
  if (!session.data) {
    return (
      <div>
        <h1 className="font-display text-3xl font-bold tracking-tight">You&apos;re invited</h1>
        <p className="mt-2 text-muted">Sign in with the email address the invitation was sent to.</p>
        <Link href={`/sign-in?next=/accept-invitation/${id}`} className={buttonClasses("primary", "lg", "mt-6 w-full")}>Continue</Link>
      </div>
    );
  }
  if (joined) return <SetPassword name={session.data.user.name} onDone={() => router.push("/home")} />;
  if (joining) return <p className="text-muted">Joining your team…</p>;
  return (
    <div>
      <h1 className="font-display text-3xl font-bold tracking-tight">Join your team on Agentry</h1>
      <p className="mt-2 text-muted">Signed in as {session.data.user.email}.</p>
      {!error && (
        <Button size="lg" className="mt-6 w-full" onClick={async () => { if (await accept()) router.push("/home"); }}>Accept invitation</Button>
      )}
      {error && (
        <div className="mt-4 space-y-3">
          <p role="alert" className="text-sm text-danger">{error}</p>
          <Link href="/home" className={buttonClasses("secondary", "md")}>Go to Agentry</Link>
        </div>
      )}
    </div>
  );
}

function SetPassword({ name, onDone }: { name: string; onDone: () => void }) {
  const [pw, setPw] = useState("");
  const [again, setAgain] = useState("");
  const [msg, setMsg] = useState<string | null>(null);
  const [pending, start] = useTransition();
  return (
    <div>
      <h1 className="font-display text-3xl font-bold tracking-tight">Welcome{name ? `, ${name.split(" ")[0]}` : ""}! You&apos;re in.</h1>
      <p className="mt-2 text-muted">Set a password to sign in next time without waiting for an email. You can also skip this and use emailed sign-in links.</p>
      <form className="mt-6 space-y-3" onSubmit={(e) => {
        e.preventDefault();
        if (pw !== again) return setMsg("The two passwords don't match");
        start(async () => {
          const r = await savePassword(pw);
          if (!r.ok) return setMsg(/already/i.test(r.error) ? "You already have a password: use it to sign in." : r.error);
          window.location.replace("/home"); // the session cookie is renewed when a password is set
        });
      }}>
        <div className="space-y-1"><Label htmlFor="new-pw">Password</Label>
          <PasswordInput id="new-pw" autoComplete="new-password" required minLength={10} value={pw} onChange={(e) => setPw(e.target.value)} /></div>
        <div className="space-y-1"><Label htmlFor="new-pw2">Password again</Label>
          <PasswordInput id="new-pw2" autoComplete="new-password" required minLength={10} value={again} onChange={(e) => setAgain(e.target.value)} /></div>
        <p className="text-xs text-muted">At least 10 characters.</p>
        {msg && <p role="alert" className="text-sm text-danger">{msg}</p>}
        <div className="flex flex-wrap gap-3">
          <Button type="submit" size="lg" disabled={pending}>Set password and continue</Button>
          <Button type="button" variant="secondary" size="lg" onClick={onDone}>Skip for now</Button>
        </div>
      </form>
    </div>
  );
}

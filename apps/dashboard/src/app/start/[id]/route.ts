import { randomUUID } from "node:crypto";
import { headers } from "next/headers";
import { type NextRequest, NextResponse } from "next/server";
import { auth, authPool, magicLinkCapture } from "@/lib/auth";
import { createOrganization, deleteOrganization } from "@/lib/clients";

const API = process.env.AGENTRY_API_URL ?? "http://localhost:8801";

/**
 * The link emailed after a website sign-up is paid (backend agentry/signups.py). Clicking it proves the email: this makes
 * the organisation and its owner (Better Auth's tables are the portal's), claims the sign-up for it once, signs the owner
 * in with a one-time link made here (never emailed), and lands on /start/{id}/finish, which switches the plan on.
 * A second click, or one after the account exists, just goes to sign-in.
 */
export async function GET(request: NextRequest, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const k = request.nextUrl.searchParams.get("k") ?? "";
  const signIn = new URL("/sign-in", request.url);
  const finish = `/start/${id}/finish?k=${encodeURIComponent(k)}`;
  const r = await fetch(`${API}/public/signups/${id}?k=${encodeURIComponent(k)}`, { cache: "no-store" });
  if (!r.ok) return NextResponse.redirect(signIn);
  const s: { status: string; business: string; name: string; email: string; org_id: string | null } = await r.json();
  if (s.status === "claimed") { signIn.searchParams.set("next", finish); return NextResponse.redirect(signIn); }
  if (s.status === "provisioned") return NextResponse.redirect(new URL("/home", request.url));  // signed out: the sign-in page first
  if (s.status !== "paid") { signIn.searchParams.set("next", "/home"); return NextResponse.redirect(signIn); }

  const email = s.email.toLowerCase();
  const existing = (await authPool.query<{ id: string; emailVerified: boolean }>(`select id, "emailVerified" from "user" where lower(email) = $1`, [email])).rows[0];
  const userId = existing?.id ?? randomUUID();
  if (!existing) {
    await authPool.query(`insert into "user" (id, name, email, "emailVerified", role, "createdAt", "updatedAt") values ($1, $2, $3, false, 'user', now(), now())`,
      [userId, s.name, email]);
  }
  const org = await createOrganization(s.business);
  const claim = await fetch(`${API}/public/signups/${id}/claim`, { method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ k, org_id: org.id }), cache: "no-store" });
  if (!claim.ok || !(await claim.json()).claimed) {  // another click got there first
    await deleteOrganization(org.id);
    signIn.searchParams.set("next", finish);
    return NextResponse.redirect(signIn);
  }
  await authPool.query(`insert into member (id, "organizationId", "userId", role, "createdAt") values ($1, $2, $3, 'owner', now())`, [randomUUID(), org.id, userId]);
  if (existing?.emailVerified) {  // someone who already uses Agentry signs in their usual way
    signIn.searchParams.set("next", finish);
    return NextResponse.redirect(signIn);
  }
  const capture: { url?: string } = {};
  const h = await headers();
  await magicLinkCapture.run(capture, () => auth.api.signInMagicLink({ body: { email, callbackURL: finish }, headers: h }));
  return NextResponse.redirect(capture.url ?? signIn);
}

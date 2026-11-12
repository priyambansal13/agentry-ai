import { headers } from "next/headers";
import { type NextRequest, NextResponse } from "next/server";
import { auth, authPool, magicLinkCapture } from "@/lib/auth";

// the portal's public address: behind the proxy request.url is the container's own (0.0.0.0:3000)
const PUBLIC = process.env.BETTER_AUTH_URL ?? "http://localhost:3201";

/**
 * The link in an invitation email. One click: it checks the invitation, signs the invited person in with a fresh
 * one-time sign-in link (made here, never emailed) and lands on the accept page, which joins them and offers to set a
 * password. It only signs in people who have never signed in before: anyone with an account uses their own sign-in.
 * Each click makes a new one-time link, so a mail scanner opening the email can't use it up.
 */
export async function GET(request: NextRequest, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const accept = new URL(`/accept-invitation/${id}`, PUBLIC);
  const inv = (await authPool.query<{ email: string; verified: boolean | null }>(
    `select i.email, u."emailVerified" as verified from invitation i left join "user" u on lower(u.email) = lower(i.email)
     where i.id = $1 and i.status = 'pending' and i."expiresAt" > now()`, [id])).rows[0];
  if (!inv) return NextResponse.redirect(accept); // accepted, cancelled or expired: the accept page explains
  if (inv.verified) {
    const signIn = new URL("/sign-in", PUBLIC);
    signIn.searchParams.set("next", `/accept-invitation/${id}`);
    return NextResponse.redirect(signIn);
  }
  const capture: { url?: string } = {};
  const h = await headers();
  await magicLinkCapture.run(capture, () => auth.api.signInMagicLink({
    body: { email: inv.email, callbackURL: `/accept-invitation/${id}?welcome=1` },
    headers: h,
  }));
  return NextResponse.redirect(capture.url ?? accept);
}

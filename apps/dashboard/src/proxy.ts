import { getSessionCookie } from "better-auth/cookies";
import { type NextRequest, NextResponse } from "next/server";

/** Optimistic check only (cookie present). Every page and API call still verifies the session server-side. */
export function proxy(request: NextRequest) {
  if (!getSessionCookie(request)) {
    const url = new URL("/sign-in", request.url);
    url.searchParams.set("next", request.nextUrl.pathname);
    return NextResponse.redirect(url);
  }
  return NextResponse.next();
}

export const config = {
  // Public files are never behind sign-in: widget.js is loaded by every client's website visitors.
  matcher: ["/((?!api/auth|sign-in|forgot-password|reset-password|accept-invitation|invite/|_next|favicon.ico|.*\\.(?:js|svg|png|jpg|ico|txt|webmanifest)$).*)"],
};

import { headers } from "next/headers";
import { auth } from "@/lib/auth";
import { getActiveOrg } from "@/lib/session";

/** Streams a video/audio/transcript upload to the API (server actions cap bodies at 11 MB; recordings are bigger). */
export async function POST(req: Request) {
  const session = await auth.api.getSession({ headers: await headers() });
  if (!session) return Response.json({ detail: "Sign in again" }, { status: 401 });
  const org = await getActiveOrg();
  if (!org) return Response.json({ detail: "No organisation selected" }, { status: 400 });
  const token = (await auth.api.getToken({ headers: await headers() })).token;
  const res = await fetch(`${process.env.AGENTRY_API_URL ?? "http://localhost:8801"}/org/content/sources`, {
    method: "POST", body: req.body, duplex: "half",
    headers: { Authorization: `Bearer ${token}`, "X-Org-Id": org.id, "Content-Type": req.headers.get("content-type") ?? "" },
  } as RequestInit);
  return new Response(await res.text(), { status: res.status, headers: { "Content-Type": "application/json" } });
}

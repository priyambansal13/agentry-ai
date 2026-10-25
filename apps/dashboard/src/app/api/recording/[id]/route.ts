import { headers } from "next/headers";
import { auth } from "@/lib/auth";
import { getActiveOrg } from "@/lib/session";

/** Streams a call recording from the API with the signed-in user's token (permissions are checked by the API). */
export async function GET(req: Request, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const org = await getActiveOrg();
  if (!org) return new Response("No organisation", { status: 400 });
  const token = (await auth.api.getToken({ headers: await headers() })).token;
  const range = req.headers.get("range");
  const res = await fetch(`${process.env.AGENTRY_API_URL ?? "http://localhost:8801"}/org/conversations/${encodeURIComponent(id)}/recording`, {
    headers: { Authorization: `Bearer ${token}`, "X-Org-Id": org.id, ...(range ? { Range: range } : {}) }, cache: "no-store",
  });
  if (!res.ok) return new Response(await res.text(), { status: res.status, headers: { "Content-Type": "application/json" } });
  const out = new Headers({ "Content-Type": "audio/ogg", "Cache-Control": "private, max-age=300" });
  for (const h of ["content-length", "content-range", "accept-ranges"]) { const v = res.headers.get(h); if (v) out.set(h, v); }
  return new Response(res.body, { status: res.status, headers: out });
}

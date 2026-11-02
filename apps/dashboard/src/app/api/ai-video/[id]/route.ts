import { headers } from "next/headers";
import { auth } from "@/lib/auth";
import { getActiveOrg } from "@/lib/session";

/** An AI video studio video, fetched with the signed-in user's token. Range requests pass through so the player can seek. */
export async function GET(req: Request, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const org = await getActiveOrg();
  if (!org) return new Response("No organisation", { status: 400 });
  const token = (await auth.api.getToken({ headers: await headers() })).token;
  const range = req.headers.get("range");
  const res = await fetch(`${process.env.AGENTRY_API_URL ?? "http://localhost:8801"}/org/videos/${encodeURIComponent(id)}/file`, {
    headers: { Authorization: `Bearer ${token}`, "X-Org-Id": org.id, ...(range ? { Range: range } : {}) }, cache: "no-store",
  });
  if (!res.ok && res.status !== 206) return new Response(null, { status: res.status });
  const out = new Headers({ "Content-Type": "video/mp4", "Cache-Control": "private, max-age=30", "Accept-Ranges": "bytes" });
  for (const h of ["content-length", "content-range", "content-disposition"]) {
    const v = res.headers.get(h);
    if (v) out.set(h, v);
  }
  return new Response(res.body, { status: res.status, headers: out });
}

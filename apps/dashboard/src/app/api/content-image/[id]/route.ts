import { headers } from "next/headers";
import { auth } from "@/lib/auth";
import { getActiveOrg } from "@/lib/session";

/** A post's quote card, fetched with the signed-in user's token (the API checks who may see it). */
export async function GET(_req: Request, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const org = await getActiveOrg();
  if (!org) return new Response("No organisation", { status: 400 });
  const token = (await auth.api.getToken({ headers: await headers() })).token;
  const res = await fetch(`${process.env.AGENTRY_API_URL ?? "http://localhost:8801"}/org/content/posts/${encodeURIComponent(id)}/image`, {
    headers: { Authorization: `Bearer ${token}`, "X-Org-Id": org.id }, cache: "no-store",
  });
  if (!res.ok) return new Response(null, { status: res.status });
  return new Response(res.body, { headers: { "Content-Type": "image/png", "Cache-Control": "private, max-age=30" } });
}

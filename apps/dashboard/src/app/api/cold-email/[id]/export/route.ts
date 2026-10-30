import { headers } from "next/headers";
import { auth } from "@/lib/auth";
import { getActiveOrg } from "@/lib/session";

/** Downloads a campaign's review sheet (CSV) from the API with the signed-in user's token; the API checks the role. */
export async function GET(req: Request, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const org = await getActiveOrg();
  if (!org) return new Response("No organisation", { status: 400 });
  const token = (await auth.api.getToken({ headers: await headers() })).token;
  const review = new URL(req.url).searchParams.get("review") === "approved" ? "approved" : "all";
  const res = await fetch(`${process.env.AGENTRY_API_URL ?? "http://localhost:8801"}/org/cold-email/campaigns/${encodeURIComponent(id)}/export.csv?review=${review}`, {
    headers: { Authorization: `Bearer ${token}`, "X-Org-Id": org.id }, cache: "no-store",
  });
  if (!res.ok) return new Response(await res.text(), { status: res.status, headers: { "Content-Type": "application/json" } });
  return new Response(res.body, { headers: { "Content-Type": "text/csv; charset=utf-8",
    "Content-Disposition": res.headers.get("content-disposition") ?? 'attachment; filename="prospects.csv"' } });
}

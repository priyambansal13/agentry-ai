import { headers } from "next/headers";
import { auth } from "@/lib/auth";
import { getActiveOrg } from "@/lib/session";

/** Streams a CSV export from the API with the signed-in user's token (the browser never sees the API token). */
export async function GET(_req: Request, { params }: { params: Promise<{ kind: string }> }) {
  const { kind } = await params;
  const org = await getActiveOrg();
  if (!org) return new Response("No organisation", { status: 400 });
  const token = (await auth.api.getToken({ headers: await headers() })).token;
  const res = await fetch(`${process.env.AGENTRY_API_URL ?? "http://localhost:8801"}/org/export/${encodeURIComponent(kind)}.csv`, {
    headers: { Authorization: `Bearer ${token}`, "X-Org-Id": org.id }, cache: "no-store",
  });
  if (!res.ok) return new Response(await res.text(), { status: res.status, headers: { "Content-Type": "application/json" } });
  return new Response(res.body, { status: res.status, headers: {
    "Content-Type": res.headers.get("content-type") ?? "text/csv",
    "Content-Disposition": res.headers.get("content-disposition") ?? `attachment; filename="${kind}.csv"`,
  } });
}

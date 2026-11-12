import { headers } from "next/headers";
import { auth } from "@/lib/auth";
import { getActiveOrg } from "@/lib/session";

/** The MSME Samadhaan claim draft for one customer, as a Markdown file to check and copy into samadhaan.msme.gov.in. */
export async function GET(_req: Request, { params }: { params: Promise<{ cid: string }> }) {
  const { cid } = await params;
  const org = await getActiveOrg();
  if (!org) return new Response("No organisation", { status: 400 });
  const token = (await auth.api.getToken({ headers: await headers() })).token;
  const res = await fetch(`${process.env.AGENTRY_API_URL ?? "http://localhost:8801"}/org/invoices/msme/claim/${encodeURIComponent(cid)}`, {
    headers: { Authorization: `Bearer ${token}`, "X-Org-Id": org.id }, cache: "no-store",
  });
  if (!res.ok) return new Response(await res.text(), { status: res.status, headers: { "Content-Type": "application/json" } });
  return new Response(await res.text(), { headers: { "Content-Type": "text/markdown; charset=utf-8",
    "Content-Disposition": `attachment; filename="msme-samadhaan-claim-${cid.slice(0, 8)}.md"` } });
}

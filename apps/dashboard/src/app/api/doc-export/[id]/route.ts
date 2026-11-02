import { headers } from "next/headers";
import { auth } from "@/lib/auth";
import { getActiveOrg } from "@/lib/session";

/** A drafted SOP, proposal or checklist as Markdown. */
export async function GET(req: Request, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const org = await getActiveOrg();
  if (!org) return new Response("No organisation", { status: 400 });
  const token = (await auth.api.getToken({ headers: await headers() })).token;
  const res = await fetch(`${process.env.AGENTRY_API_URL ?? "http://localhost:8801"}/org/docs/${encodeURIComponent(id)}/export`, {
    headers: { Authorization: `Bearer ${token}`, "X-Org-Id": org.id }, cache: "no-store" });
  if (!res.ok) return new Response(await res.text(), { status: res.status });
  return new Response(res.body, { headers: { "Content-Type": res.headers.get("content-type") ?? "text/plain",
    "Content-Disposition": res.headers.get("content-disposition") ?? "attachment" } });
}

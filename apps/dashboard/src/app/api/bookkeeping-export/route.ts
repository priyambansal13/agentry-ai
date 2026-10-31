import { headers } from "next/headers";
import { auth } from "@/lib/auth";
import { getActiveOrg } from "@/lib/session";

/** Tally XML or CSV of the filed receipts and bills (only ones not exported before, unless include_exported=true). */
export async function GET(req: Request) {
  const org = await getActiveOrg();
  if (!org) return new Response("No organisation", { status: 400 });
  const token = (await auth.api.getToken({ headers: await headers() })).token;
  const q = new URL(req.url).searchParams;
  const keep = new URLSearchParams([...q.entries()].filter(([k]) => ["format", "month", "include_exported"].includes(k)));
  const res = await fetch(`${process.env.AGENTRY_API_URL ?? "http://localhost:8801"}/org/bookkeeping/export?${keep}`, {
    headers: { Authorization: `Bearer ${token}`, "X-Org-Id": org.id }, cache: "no-store",
  });
  if (!res.ok) return new Response(await res.text(), { status: res.status, headers: { "Content-Type": "application/json" } });
  return new Response(res.body, { headers: {
    "Content-Type": res.headers.get("content-type") ?? "text/csv",
    "Content-Disposition": res.headers.get("content-disposition") ?? 'attachment; filename="expenses.csv"',
  } });
}

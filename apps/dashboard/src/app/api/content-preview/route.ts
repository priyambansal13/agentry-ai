import { headers } from "next/headers";
import { auth } from "@/lib/auth";
import { getActiveOrg } from "@/lib/session";

/** A sample quote card in the current brand kit. */
export async function GET(req: Request) {
  const org = await getActiveOrg();
  if (!org) return new Response("No organisation", { status: 400 });
  const platform = new URL(req.url).searchParams.get("platform") === "linkedin" ? "linkedin" : "instagram";
  const token = (await auth.api.getToken({ headers: await headers() })).token;
  const res = await fetch(`${process.env.AGENTRY_API_URL ?? "http://localhost:8801"}/org/content/brand/preview?platform=${platform}`, {
    headers: { Authorization: `Bearer ${token}`, "X-Org-Id": org.id }, cache: "no-store",
  });
  if (!res.ok) return new Response(null, { status: res.status });
  return new Response(res.body, { headers: { "Content-Type": "image/png", "Cache-Control": "no-store" } });
}

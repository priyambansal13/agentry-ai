import { headers } from "next/headers";
import { auth } from "@/lib/auth";
import { getActiveOrg } from "@/lib/session";

// downloads from the CA desk: a client's file, or a sheet the CA agents made (tax.xlsx, reconciliations…)
const ALLOWED = [/^files\/[0-9a-f-]{36}$/, /^clients\/[0-9a-f-]{36}\/[a-z0-9-]+\.(xlsx|csv|json)$/, /^[a-z0-9-]+\/[0-9a-f-]{36}\.(xlsx|csv)$/];

export async function GET(req: Request, { params }: { params: Promise<{ path: string[] }> }) {
  const org = await getActiveOrg();
  if (!org) return new Response("No organisation", { status: 400 });
  const path = (await params).path.join("/");
  if (!ALLOWED.some((r) => r.test(path))) return new Response("Not found", { status: 404 });
  const token = (await auth.api.getToken({ headers: await headers() })).token;
  const res = await fetch(`${process.env.AGENTRY_API_URL ?? "http://localhost:8801"}/org/ca/${path}${new URL(req.url).search}`, {
    headers: { Authorization: `Bearer ${token}`, "X-Org-Id": org.id }, cache: "no-store",
  });
  if (!res.ok) return new Response(await res.text(), { status: res.status, headers: { "Content-Type": "application/json" } });
  const h = new Headers({ "Content-Type": res.headers.get("content-type") ?? "application/octet-stream" });
  const cd = res.headers.get("content-disposition");
  if (cd) h.set("Content-Disposition", cd);
  return new Response(res.body, { headers: h });
}

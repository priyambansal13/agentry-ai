/** Unlisted, for the dev team: the version of the website that's running and when it was deployed
 *  (AGENTRY_TAG / AGENTRY_DEPLOYED_AT, set by infra/deploy-oracle.sh). Not linked anywhere, not indexed. */
export const dynamic = "force-dynamic";

export function GET() {
  const tag = process.env.AGENTRY_TAG ?? "local";
  const at = process.env.AGENTRY_DEPLOYED_AT;
  const when = at ? new Date(at).toLocaleString("en-IN", { timeZone: "Asia/Kolkata", dateStyle: "medium", timeStyle: "short" }) + " IST" : "unknown";
  return new Response(`${tag} · deployed ${when}\n`, {
    headers: { "Content-Type": "text/plain; charset=utf-8", "Cache-Control": "no-store", "X-Robots-Tag": "noindex, nofollow" },
  });
}

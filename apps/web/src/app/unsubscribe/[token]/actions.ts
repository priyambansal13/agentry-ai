"use server";

const API = process.env.AGENTRY_API_URL ?? "http://localhost:8801";

export async function confirmUnsubscribe(token: string): Promise<boolean> {
  const r = await fetch(`${API}/public/unsubscribe/${encodeURIComponent(token)}`, { method: "POST", cache: "no-store" });
  return r.ok;
}

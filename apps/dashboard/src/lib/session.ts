import "server-only";
import { cookies, headers } from "next/headers";
import { notFound, redirect } from "next/navigation";
import { cache } from "react";
import { auth } from "./auth";

export type OrgSummary = { id: string; name: string; slug: string; role: string; role_label: string; status: string; viewing_as_staff?: boolean };

/** Agentry staff can open any client's portal (HQ → Open portal). The choice lives in this cookie. */
export const VIEW_AS_COOKIE = "agentry_view_org";
export type Me = {
  user: { id: string; email: string; name: string };
  is_staff: boolean;
  organizations: OrgSummary[];
};

const API = process.env.AGENTRY_API_URL ?? "http://localhost:8801";

export const getSession = cache(async () => {
  const session = await auth.api.getSession({ headers: await headers() });
  if (!session) redirect("/sign-in");
  return session;
});

/** Short-lived JWT for the Python API, minted from the Better Auth session. A session that has ended (expired, signed
 *  out elsewhere, password changed) sends the person to sign in instead of failing the page. */
const getToken = cache(async () => {
  await getSession();
  try {
    return (await auth.api.getToken({ headers: await headers() })).token;
  } catch {
    redirect("/sign-in");
  }
});

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

export async function api<T>(path: string, init: { orgId?: string; method?: string; body?: unknown } = {}): Promise<T> {
  const res = await fetch(`${API}${path}`, {
    method: init.method ?? "GET",
    headers: {
      Authorization: `Bearer ${await getToken()}`,
      ...(init.orgId ? { "X-Org-Id": init.orgId } : {}),
      ...(init.body ? { "Content-Type": "application/json" } : {}),
    },
    body: init.body ? JSON.stringify(init.body) : undefined,
    cache: "no-store",
  });
  if (!res.ok) throw new ApiError(res.status, await res.text());
  return res.json() as Promise<T>;
}

export const getMe = cache(() => api<Me>("/me"));

/** The organisation being viewed: for Agentry staff, a client opened from HQ; otherwise the session's active org if the
 *  user still belongs to it, else their first. */
export const getActiveOrg = cache(async (): Promise<OrgSummary | null> => {
  const [session, me] = await Promise.all([getSession(), getMe()]);
  if (me.is_staff) {
    const viewId = (await cookies()).get(VIEW_AS_COOKIE)?.value;
    if (viewId && !me.organizations.some((o) => o.id === viewId)) {
      const p = await api<{ name: string; status: string }>("/org/profile", { orgId: viewId }).catch(() => null);
      if (p) return { id: viewId, name: p.name, slug: "", role: "agentry_staff", role_label: "Agentry staff view", status: p.status, viewing_as_staff: true };
    }
  }
  const activeId = (session.session as { activeOrganizationId?: string | null }).activeOrganizationId;
  return me.organizations.find((o) => o.id === activeId) ?? me.organizations[0] ?? null;
});

export type Features = { automations: string[]; pages: string[]; connections: string[]; steps: string[]; go_live: string[] };

/** What the active client bought decides what the portal shows (backend: agentry/features.py). */
export const getFeatures = cache(async (orgId: string): Promise<Features> => api<Features>("/org/features", { orgId }));

/** Page guard: a section that isn't part of this client's automations doesn't exist for them. */
export async function requirePage(page: string): Promise<OrgSummary> {
  const active = await getActiveOrg();
  if (!active) redirect("/home");
  if (!(await getFeatures(active.id)).pages.includes(page)) notFound();
  return active;
}

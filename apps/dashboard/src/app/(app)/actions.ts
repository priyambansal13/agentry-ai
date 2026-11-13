"use server";

import { cookies, headers } from "next/headers";
import { redirect } from "next/navigation";
import { revalidatePath } from "next/cache";
import { auth } from "@/lib/auth";
import { cancelInvitation, createOrganization, deleteOrganization, inviteToOrganization, updateMember } from "@/lib/clients";
import { can } from "@/lib/permissions";
import { api, ApiError, getActiveOrg, getMe, VIEW_AS_COOKIE } from "@/lib/session";

export type ActionResult<T = unknown> = { ok: true; data: T } | { ok: false; error: string };

async function run<T>(path: string, init: { method: string; body?: unknown }, revalidate: string[] = []): Promise<ActionResult<T>> {
  const org = await getActiveOrg();
  if (!org) return { ok: false, error: "No organisation selected" };
  try {
    const data = await api<T>(path, { ...init, orgId: org.id });
    revalidate.forEach((p) => revalidatePath(p));
    return { ok: true, data };
  } catch (e) {
    if (e instanceof ApiError) {
      let msg = e.message;
      try {
        const d = JSON.parse(e.message).detail;
        msg = typeof d === "string" ? d : Array.isArray(d) ? d.map((x: { msg?: string }) => x.msg).join("; ") : msg;
      } catch { /* plain text */ }
      return { ok: false, error: msg };
    }
    return { ok: false, error: "Something went wrong" };
  }
}

export async function decideApproval(id: string, action: "approve" | "reject" | "resolve", body?: string) {
  return run(`/org/approvals/${id}`, { method: "POST", body: { action, body } }, ["/needs-you", "/home", "/conversations"]);
}

export async function setAutomationState(key: string, action: "pause" | "resume" | "automatic" | "approval") {
  return run(`/org/automations/${key}/${action}`, { method: "POST" }, ["/automations", `/automations/${key}`, "/home"]);
}

export async function updateAutomationConfig(key: string, changes: Record<string, unknown>) {
  return run(`/org/automations/${key}/config`, { method: "PATCH", body: changes }, [`/automations/${key}`]);
}

export async function updateProfile(changes: Record<string, unknown>) {
  return run("/org/profile", { method: "PATCH", body: changes }, ["/onboarding", "/home"]);
}

export async function setPersona(persona: { name: string; tone: string; greeting: string; signoff?: string }) {
  return run("/org/persona", { method: "PUT", body: persona }, ["/onboarding"]);
}

export async function addFaq(q: string, a: string) {
  return run("/org/knowledge/faqs", { method: "POST", body: { q, a } }, ["/knowledge", "/onboarding"]);
}

export async function learnWebsite(url: string) {
  return run<{ pages_learned: number }>("/org/knowledge/website", { method: "POST", body: { url } }, ["/knowledge", "/onboarding"]);
}

export async function deleteKnowledge(id: string) {
  return run(`/org/knowledge/${id}`, { method: "DELETE" }, ["/knowledge"]);
}

export async function markStep(step: string, status: "done" | "skipped" | "todo") {
  return run(`/org/onboarding/${step}`, { method: "PUT", body: { status } }, ["/onboarding", "/home"]);
}

export async function testAgent(text: string, conversationId?: string) {
  return run<{ conversation_id: string; reply: string; booking: { service: string; when: string; staff: string } | null }>(
    "/org/agent/test", { method: "POST", body: { text, conversation_id: conversationId } });
}

export async function goLive() {
  return run<{ live: boolean; approval_mode: string[] }>("/org/go-live", { method: "POST" }, ["/onboarding", "/home", "/automations"]);
}

/** Agentry HQ: create a demo organisation (Better Auth, as the signed-in staff member) and build it. */
export async function createDemo(url: string, pack: string): Promise<ActionResult<{ slug: string; name: string; pages_learned: number }>> {
  try {
    const preview = await api<{ name: string }>("/hq/demos/preview", { method: "POST", body: { url } });
    const slug = `${preview.name.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "").slice(0, 40)}-${Math.random().toString(36).slice(2, 6)}`;
    const org = await auth.api.createOrganization({
      body: { name: preview.name, slug, keepCurrentActiveOrganization: true },
      headers: await headers(),
    });
    if (!org) return { ok: false, error: "Could not create the demo organisation" };
    const built = await api<{ slug: string; name: string; pages_learned: number }>("/hq/demos", {
      method: "POST", body: { org_id: org.id, url, pack },
    });
    revalidatePath("/hq/demos");
    return { ok: true, data: built };
  } catch (e) {
    const msg = e instanceof ApiError ? (() => { try { return JSON.parse(e.message).detail; } catch { return e.message; } })() : String(e);
    return { ok: false, error: typeof msg === "string" ? msg : "Could not build the demo" };
  }
}

// ---------- connections ----------

export async function startGmail() {
  return run<{ url: string }>("/org/connections/gmail/start", { method: "POST" });
}

export async function syncGmail() {
  return run<{ new_emails: number }>("/org/connections/gmail/sync", { method: "POST" }, ["/settings/connections", "/conversations"]);
}

export async function disconnect(id: string) {
  return run(`/org/connections/${id}`, { method: "DELETE" }, ["/settings/connections"]);
}

export async function connectWhatsApp(phone_number_id: string, waba_id: string, access_token: string) {
  return run<{ display: string; verified_name: string }>("/org/connections/whatsapp", { method: "POST", body: { phone_number_id, waba_id, access_token } }, ["/settings/connections", "/automations"]);
}

export async function testWhatsApp(to: string) {
  return run<{ sent: boolean }>("/org/connections/whatsapp/test", { method: "POST", body: { to } });
}

// ---------- invoices, campaigns, lead forms, gateways ----------

async function upload<T>(path: string, form: FormData, revalidate: string[] = []): Promise<ActionResult<T>> {
  const org = await getActiveOrg();
  if (!org) return { ok: false, error: "No organisation selected" };
  const token = (await auth.api.getToken({ headers: await headers() })).token;
  const res = await fetch(`${process.env.AGENTRY_API_URL ?? "http://localhost:8801"}${path}`, {
    method: "POST", body: form, headers: { Authorization: `Bearer ${token}`, "X-Org-Id": org.id }, cache: "no-store",
  });
  const body = await res.json().catch(() => ({}));
  if (!res.ok) return { ok: false, error: typeof body.detail === "string" ? body.detail : "Upload failed" };
  revalidate.forEach((p) => revalidatePath(p));
  return { ok: true, data: body as T };
}

export async function importInvoices(form: FormData) {
  return upload<Record<string, unknown>>("/org/invoices/import", form, ["/invoices", "/home"]);
}

export async function recordPayment(invoiceId: string, amount: number, reference: string) {
  return run(`/org/invoices/${invoiceId}/payments`, { method: "POST", body: { amount, reference } }, ["/invoices", "/home"]);
}

export async function invoiceReminders(invoiceId: string, action: "pause" | "resume" | "stop") {
  return run(`/org/invoices/${invoiceId}/reminders/${action}`, { method: "POST" }, ["/invoices"]);
}

export async function importOldLeads(form: FormData) {
  return upload<Record<string, unknown>>("/org/campaigns/reactivation/import", form, ["/campaigns", "/leads"]);
}

export async function startReactivation(name: string, perHour: number) {
  return run<{ enrolled: number; finishes_at: string }>("/org/campaigns/reactivation", { method: "POST", body: { name, per_hour: perHour } }, ["/campaigns", "/leads"]);
}

export async function addLeadSource(name: string) {
  return run<{ url: string }>("/org/lead-sources", { method: "POST", body: { name } }, ["/leads"]);
}

export async function connectRazorpay(key_id: string, key_secret: string, webhook_secret: string) {
  return run<{ webhook_url: string; events: string[] }>("/org/connections/razorpay", { method: "POST", body: { key_id, key_secret, webhook_secret } }, ["/settings/connections"]);
}

export async function connectStripe(webhook_secret: string, secret_key?: string) {
  return run<{ webhook_url: string; events: string[] }>("/org/connections/stripe", { method: "POST", body: { webhook_secret, secret_key: secret_key || null } }, ["/settings/connections"]);
}

export async function invoiceStatus(id: string, action: "reopen" | "write_off" | "void", note?: string) {
  return run<{ status: string }>(`/org/invoices/${id}/status`, { method: "POST", body: { action, note: note || null } }, ["/invoices", "/needs-you"]);
}

export async function confirmPayment(approvalId: string, invoiceId?: string) {
  return run("/org/payments/confirm", { method: "POST", body: { approval_id: approvalId, invoice_id: invoiceId ?? null } }, ["/invoices", "/needs-you"]);
}

// ---------- billing, notifications ----------

export async function disputeLine(lineId: string, reason: string) {
  return run(`/org/billing/lines/${lineId}/dispute`, { method: "POST", body: { reason } }, ["/billing"]);
}

export async function saveNotificationPrefs(prefs: Record<string, string[]>) {
  return run("/org/notifications", { method: "PUT", body: prefs });
}

// ---------- Agentry HQ billing (staff only; the API enforces it) ----------

async function hq<T>(path: string, init: { method: string; body?: unknown }, revalidate: string[]): Promise<ActionResult<T>> {
  try {
    const data = await api<T>(path, init);
    revalidate.forEach((p) => revalidatePath(p));
    return { ok: true, data };
  } catch (e) {
    if (e instanceof ApiError) {
      try {
        const d = JSON.parse(e.message).detail;
        return { ok: false, error: typeof d === "string" ? d : Array.isArray(d) ? d.map((x: { loc?: string[]; msg?: string }) => `${x.loc?.slice(1).join(".")}: ${x.msg}`).join("; ") : e.message };
      } catch { return { ok: false, error: e.message }; }
    }
    return { ok: false, error: "Something went wrong" };
  }
}

export async function hqSavePlan(orgId: string, plan: unknown) {
  return hq(`/hq/orgs/${orgId}/plan`, { method: "PUT", body: plan }, [`/hq/${orgId}`]);
}

export async function hqGenerateStatement(orgId: string, month: string) {
  return hq<{ statement_id: string }>(`/hq/orgs/${orgId}/statements`, { method: "POST", body: { month } }, [`/hq/${orgId}`]);
}

export async function hqIssueStatement(orgId: string, sid: string) {
  return hq(`/hq/orgs/${orgId}/statements/${sid}/issue`, { method: "POST" }, [`/hq/${orgId}`, `/hq/${orgId}/statements/${sid}`]);
}

export async function hqResolveDispute(orgId: string, sid: string, lineId: string, accept: boolean,
                                       partial?: { credit: number; note: string; exclude_outcomes: string[] }) {
  return hq(`/hq/orgs/${orgId}/lines/${lineId}/resolve`, { method: "POST", body: partial ?? { accept } },
            [`/hq/${orgId}`, `/hq/${orgId}/statements/${sid}`]);
}

// ---------- Agentry HQ: onboarding clients ----------

export type NewClientInput = {
  name: string; country: string; timezone: string; currency: string; website: string;
  automations: string[]; owner: { name: string; email: string } | null; plan: unknown | null;
  pack?: string | null; pack_agents?: string[] | null; // docs/PACKS.md: a pack tailored to them; automations = add-ons
};

export async function hqCreateClient(input: NewClientInput): Promise<ActionResult<{ orgId: string; invite: string | null }>> {
  const me = await getMe();
  if (!me.is_staff) return { ok: false, error: "Agentry staff only" };
  if (input.name.trim().length < 2) return { ok: false, error: "Enter the business name" };
  if (!input.automations.length && !input.pack) return { ok: false, error: "Choose a pack or at least one automation" };
  const org = await createOrganization(input.name.trim());
  const res = await hq<{ org_id: string }>("/hq/clients", { method: "POST", body: {
    org_id: org.id, country: input.country, timezone: input.timezone, currency: input.currency,
    website: input.website.trim() || null, automations: input.automations, plan: input.plan,
    pack: input.pack || null, pack_agents: input.pack ? input.pack_agents ?? null : null,
  } }, ["/hq"]);
  if (!res.ok) {
    await deleteOrganization(org.id); // nothing half-created is left behind
    return res;
  }
  let invite: string | null = null;
  if (input.owner?.email) {
    invite = await inviteToOrganization({ orgId: org.id, orgName: input.name.trim(), email: input.owner.email, name: input.owner.name,
                                          role: "owner", inviterId: me.user.id, inviterName: `${me.user.name} (Agentry)` });
  }
  return { ok: true, data: { orgId: org.id, invite } };
}

export async function hqInvite(orgId: string, orgName: string, email: string, role: string, name = ""): Promise<ActionResult<string>> {
  const me = await getMe();
  if (!me.is_staff) return { ok: false, error: "Agentry staff only" };
  if (!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(email)) return { ok: false, error: "Enter a valid email" };
  if (!["owner", "manager", "staff", "finance", "viewer"].includes(role)) return { ok: false, error: "Unknown role" };
  const r = await inviteToOrganization({ orgId, orgName, email, name, role, inviterId: me.user.id, inviterName: `${me.user.name} (Agentry)` });
  revalidatePath(`/hq/${orgId}`);
  return { ok: true, data: r };
}

export async function hqSwitchAutomation(orgId: string, key: string, enabled: boolean) {
  return hq<{ automations: string[] }>(`/hq/orgs/${orgId}/automations/${key}`, { method: "PUT", body: { enabled } }, [`/hq/${orgId}`]);
}

// ---------- packs (docs/PACKS.md) ----------

export async function hqSavePack(key: string, body: unknown, create: boolean) {
  return hq<{ key: string }>(create ? "/hq/agent-packs" : `/hq/agent-packs/${key}`,
    { method: create ? "POST" : "PUT", body: create ? { ...(body as object), key } : body }, ["/hq/packs"]);
}

export async function hqAssignPack(orgId: string, pack: string, agents: string[], applyPricing: boolean) {
  return hq<{ automations: string[] }>(`/hq/orgs/${orgId}/pack`, { method: "PUT", body: { pack, agents, apply_pricing: applyPricing } }, [`/hq/${orgId}`]);
}

export async function hqRemovePack(orgId: string, keepAgents: boolean) {
  return hq<{ automations: string[] }>(`/hq/orgs/${orgId}/pack?keep_agents=${keepAgents}`, { method: "DELETE" }, [`/hq/${orgId}`]);
}

export async function openClientPortal(orgId: string, to = "/home") {
  const me = await getMe();
  if (!me.is_staff) return;
  await api(`/hq/orgs/${orgId}/open`, { method: "POST" }); // recorded in the client's audit log
  (await cookies()).set(VIEW_AS_COOKIE, orgId, { httpOnly: true, sameSite: "lax", path: "/", maxAge: 60 * 60 * 8 });
  redirect(to);
}

export async function exitClientView() {
  (await cookies()).delete(VIEW_AS_COOKIE);
  redirect("/hq");
}

// ---------- team (owners manage their team; Agentry staff can do it for them) ----------

const ROLE_KEYS = ["owner", "manager", "staff", "finance", "viewer"];

async function teamGuard(resource: string, action: string) {
  const [me, active] = await Promise.all([getMe(), getActiveOrg()]);
  if (!active) return { error: "No organisation selected" } as const;
  if (!(me.is_staff || can(active.role, resource, action))) return { error: "You don't have permission to do that" } as const;
  return { me, active } as const;
}

async function recordTeam(orgId: string, action: string, email: string, role?: string) {
  await api("/org/team/events", { orgId, method: "POST", body: { action, email, role } }).catch(() => undefined);
}

export async function teamInvite(email: string, name: string, role: string): Promise<ActionResult<string>> {
  const g = await teamGuard("invitation", "create");
  if ("error" in g) return { ok: false, error: g.error! };
  if (!ROLE_KEYS.includes(role)) return { ok: false, error: "Unknown role" };
  if (!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(email)) return { ok: false, error: "Enter a valid email" };
  const r = await inviteToOrganization({ orgId: g.active.id, orgName: g.active.name, email, name, role, inviterId: g.me.user.id,
                                         inviterName: g.me.is_staff ? `${g.me.user.name} (Agentry)` : g.me.user.name });
  await recordTeam(g.active.id, r === "added" ? "member.added" : "member.invited", email, role);
  revalidatePath("/team");
  return { ok: true, data: r };
}

export async function teamChangeRole(memberId: string, role: string): Promise<ActionResult> {
  const g = await teamGuard("member", "update");
  if ("error" in g) return { ok: false, error: g.error! };
  if (!ROLE_KEYS.includes(role)) return { ok: false, error: "Unknown role" };
  try {
    const { email } = await updateMember(g.active.id, memberId, { role });
    await recordTeam(g.active.id, "member.role_changed", email, role);
  } catch (e) { return { ok: false, error: (e as Error).message }; }
  revalidatePath("/team");
  return { ok: true, data: null };
}

export async function teamRemove(memberId: string): Promise<ActionResult> {
  const g = await teamGuard("member", "delete");
  if ("error" in g) return { ok: false, error: g.error! };
  try {
    const { email } = await updateMember(g.active.id, memberId, "remove");
    await recordTeam(g.active.id, "member.removed", email);
  } catch (e) { return { ok: false, error: (e as Error).message }; }
  revalidatePath("/team");
  return { ok: true, data: null };
}

export async function teamCancelInvite(invitationId: string): Promise<ActionResult> {
  const g = await teamGuard("invitation", "cancel");
  if ("error" in g) return { ok: false, error: g.error! };
  try {
    const { email } = await cancelInvitation(g.active.id, invitationId);
    await recordTeam(g.active.id, "invitation.canceled", email);
  } catch (e) { return { ok: false, error: (e as Error).message }; }
  revalidatePath("/team");
  return { ok: true, data: null };
}

// ---------- conversations: a person replies, takes over, hands back ----------

export async function replyInConversation(conversationId: string, body: string) {
  return run<{ message_id: string }>(`/org/conversations/${conversationId}/reply`, { method: "POST", body: { body } },
                                     [`/conversations/${conversationId}`, "/needs-you"]);
}

export async function setConversationStatus(conversationId: string, status: "open" | "handed_off" | "closed") {
  return run(`/org/conversations/${conversationId}/status`, { method: "POST", body: { status } }, [`/conversations/${conversationId}`, "/needs-you"]);
}

// ---------- your password (email-link-only people can add one; others change theirs) ----------

export async function savePassword(newPassword: string, currentPassword?: string): Promise<ActionResult> {
  if (newPassword.length < 10) return { ok: false, error: "Use at least 10 characters" };
  const h = await headers();
  try {
    if (currentPassword) {
      await auth.api.changePassword({ body: { currentPassword, newPassword, revokeOtherSessions: false }, headers: h });
      // sign out other devices, keeping this session (revoking inside changePassword rotates it mid-request)
      await auth.api.revokeOtherSessions({ headers: h });
    } else {
      await auth.api.setPassword({ body: { newPassword }, headers: h });
    }
    return { ok: true, data: null };
  } catch (e) {
    const msg = (e as { body?: { message?: string } }).body?.message ?? (e as Error).message;
    return { ok: false, error: /invalid password/i.test(msg) ? "Your current password is wrong" : msg || "Couldn't save the password" };
  }
}


// ---------- knowledge: pasted text and uploaded files ----------

export async function addKnowledgeText(title: string, content: string) {
  return run<{ id: string }>("/org/knowledge/text", { method: "POST", body: { title, content } }, ["/knowledge", "/onboarding"]);
}

export async function uploadKnowledgeFile(form: FormData) {
  return upload<{ id: string; characters: number }>("/org/knowledge/file", form, ["/knowledge", "/onboarding"]);
}

// ---------- voice test console (Phase 4.1) ----------

export async function startTestCall() {
  return run<{ url: string; token: string; room: string; conversation_id: string; agent: string }>("/org/voice/test-call", { method: "POST" });
}

export async function deleteRecording(conversationId: string) {
  return run(`/org/conversations/${conversationId}/recording`, { method: "DELETE" }, [`/conversations/${conversationId}`]);
}

export async function saveVoiceSettings(recording_retention_days: number) {
  return run("/org/voice/settings", { method: "PUT", body: { recording_retention_days } }, ["/talk"]);
}

export async function hqAssignPhone(orgId: string, number: string) {
  return hq<{ number: string }>(`/hq/orgs/${orgId}/phone`, { method: "PUT", body: { number } }, [`/hq/${orgId}`]);
}

export async function hqUnassignPhone(orgId: string, number: string) {
  return hq(`/hq/orgs/${orgId}/phone/${encodeURIComponent(number)}`, { method: "DELETE" }, [`/hq/${orgId}`]);
}

// ---------- Agentry's own demo requests (HQ) ----------

export type DemoRequestPatch = { status?: string; notes?: string; demo_org_id?: string; client_org_id?: string };

export async function hqUpdateDemoRequest(id: string, patch: DemoRequestPatch) {
  return hq(`/hq/demo-requests/${id}`, { method: "PATCH", body: patch }, ["/hq", `/hq/demo-requests/${id}`]);
}

export async function hqBuildDemoFromRequest(id: string, url: string, pack: string): Promise<ActionResult<{ slug: string }>> {
  const built = await createDemo(url, pack);
  if (!built.ok) return built;
  const org = await api<{ items: { id: string; slug: string }[] }>("/hq/demos").then((r) => r.items.find((d) => d.slug === built.data.slug));
  if (!org) return { ok: false, error: "Demo built, but couldn't link it to the request" };
  const linked = await hqUpdateDemoRequest(id, { demo_org_id: org.id });
  return linked.ok ? { ok: true, data: { slug: built.data.slug } } : linked;
}

export async function hqPreviewDemoEmail(id: string, video_url: string, note: string) {
  return hq<{ to: string; subject: string; body: string }>(`/hq/demo-requests/${id}/preview-email`,
    { method: "POST", body: { video_url: video_url || null, note: note || null } }, []);
}

export async function hqSendDemo(id: string, video_url: string, note: string) {
  return hq(`/hq/demo-requests/${id}/send`, { method: "POST", body: { video_url: video_url || null, note: note || null } },
    ["/hq", `/hq/demo-requests/${id}`]);
}

export async function hqSendProposal(input: { email: string; note: string; snapshot: unknown; plan: unknown; demo_request_id: string | null }) {
  return hq<{ id: string; url: string }>("/hq/proposals", { method: "POST", body: { ...input, note: input.note || null } },
    input.demo_request_id ? [`/hq/demo-requests/${input.demo_request_id}`] : []);
}

// ---------- Needs you: snooze, saved replies ----------

export async function snoozeApproval(id: string, until: string | null) {
  return run(`/org/approvals/${id}/snooze`, { method: "POST", body: { until } }, ["/needs-you", "/home"]);
}

export async function saveReplyTemplate(title: string, body: string) {
  return run<{ id: string }>("/org/reply-templates", { method: "POST", body: { title, body } }, ["/saved-replies", "/needs-you"]);
}

export async function updateReplyTemplate(id: string, title: string, body: string) {
  return run(`/org/reply-templates/${id}`, { method: "PUT", body: { title, body } }, ["/saved-replies", "/needs-you"]);
}

export async function deleteReplyTemplate(id: string) {
  return run(`/org/reply-templates/${id}`, { method: "DELETE" }, ["/saved-replies", "/needs-you"]);
}

export async function recategorise(conversationId: string, category: string) {
  return run<{ category: string; previous: string }>(`/org/conversations/${conversationId}/category`, { method: "POST", body: { category } },
    [`/conversations/${conversationId}`, "/conversations"]);
}

export async function assignApproval(id: string, userId: string | null) {
  return run(`/org/approvals/${id}/assign`, { method: "POST", body: { user_id: userId } }, ["/needs-you"]);
}

export async function saveWhatsAppNumber(number: string) {
  return run<{ whatsapp_to: string | null }>("/org/notifications/whatsapp", { method: "PUT", body: { number: number || null } }, ["/settings/account"]);
}

export async function setInboxRouting(connectionId: string, assignTo: string | null) {
  return run(`/org/connections/${connectionId}/routing`, { method: "PUT", body: { assign_to: assignTo } }, ["/settings/connections"]);
}

export async function setAlertTemplate(connectionId: string, template: string, language: string) {
  return run(`/org/connections/${connectionId}/alert-template`, { method: "PUT", body: { template: template || null, language } }, ["/settings/connections"]);
}

export async function relearnStyle() {
  return run<{ learned: boolean; samples: number; reason?: string }>("/org/inbox/learn-style", { method: "POST" }, ["/automations/inbox_triage"]);
}

export async function startOutlook() {
  return run<{ url: string }>("/org/connections/outlook/start", { method: "POST" });
}

export async function syncOutlook() {
  return run<{ new_emails: number }>("/org/connections/outlook/sync", { method: "POST" }, ["/settings/connections"]);
}

// ---------- cold email (Phase 5.1-5.3) ----------

export type NewColdCampaign = { name: string; query: string; city: string; limit: number; min_rating?: number | null; min_reviews?: number | null };

export async function createColdCampaign(body: NewColdCampaign) {
  return run<{ id: string }>("/org/cold-email/campaigns", { method: "POST", body }, ["/cold-email"]);
}

export async function uploadColdCampaign(form: FormData) {
  return upload<{ id: string; businesses: number }>("/org/cold-email/campaigns/csv", form, ["/cold-email"]);
}

export async function reviewProspect(id: string, action: "approve" | "drop" | "reopen", firstLine?: string) {
  return run<{ review: string; edited: boolean }>(`/org/cold-email/prospects/${id}`, { method: "POST", body: { action, first_line: firstLine || null } }, []);
}

export async function approveReadyLines(campaignId: string) {
  return run<{ approved: number }>(`/org/cold-email/campaigns/${campaignId}/approve-ready`, { method: "POST" }, [`/cold-email/${campaignId}`]);
}

// ---------- auto-assign rules ----------

export type RoutingRule = { scope: "contact" | "automation"; key: string; assign_to: string; resources: string[]; assign_name: string | null;
                            contact_name: string | null };

export async function setCardRouting(scope: "contact" | "automation", key: string, assignTo: string | null) {
  return run<{ items: RoutingRule[]; cards_assigned: number }>("/org/card-routing", { method: "PUT", body: { scope, key, assign_to: assignTo } },
    ["/needs-you", "/invoices", "/automations"]);
}

export async function startColdCampaign(campaignId: string) {
  return run<{ queued: number }>(`/org/cold-email/campaigns/${campaignId}/start`, { method: "POST" }, [`/cold-email/${campaignId}`, "/cold-email"]);
}

export async function pauseColdCampaign(campaignId: string, action: "pause" | "resume") {
  return run<{ status: string }>(`/org/cold-email/campaigns/${campaignId}/${action}`, { method: "POST" }, [`/cold-email/${campaignId}`, "/cold-email"]);
}

export async function simulateColdReply(prospectId: string, replyText: string, complaint = false) {
  return run<{ kind?: string; mailbox_paused?: string | null }>(`/org/cold-email/prospects/${prospectId}/simulate-reply`,
    { method: "POST", body: { text: replyText || "spam", complaint } }, ["/needs-you"]);
}

export async function addSendingMailbox(orgId: string, address: string, senderName: string, dailyCap: number) {
  return hq<{ id: string }>(`/hq/orgs/${orgId}/sending-mailboxes`, { method: "POST", body: { address, sender_name: senderName, daily_cap: dailyCap } }, [`/hq/${orgId}`]);
}

export async function changeSendingMailbox(orgId: string, mailboxId: string, status: "active" | "paused") {
  return hq<{ id: string }>(`/hq/orgs/${orgId}/sending-mailboxes/${mailboxId}`, { method: "PATCH", body: { status } }, [`/hq/${orgId}`]);
}

// ---------- content repurposing (Phase 6) ----------

export async function addContentLink(url: string, title: string, ownsRights: boolean) {
  return run<{ id: string; title: string | null }>("/org/content/sources/link", { method: "POST", body: { url, title: title || null, owns_rights: ownsRights } }, ["/content"]);
}

export async function sampleContent() {
  return run<{ id: string }>("/org/content/sources/sample", { method: "POST" }, ["/content"]);
}

export async function retryContent(id: string) {
  return run<{ id: string }>(`/org/content/sources/${id}/retry`, { method: "POST" }, [`/content/${id}`]);
}

export async function deleteContent(id: string) {
  return run<{ deleted: boolean }>(`/org/content/sources/${id}`, { method: "DELETE" }, ["/content"]);
}

export async function reviewContentPost(id: string, action: "approve" | "drop" | "reopen" | "regenerate", body?: string) {
  return run<{ review: string; edited?: boolean }>(`/org/content/posts/${id}`, { method: "POST", body: { action, body: body || null } }, []);
}

export async function dropContentMoment(id: string) {
  return run<{ dropped_posts: number }>(`/org/content/moments/${id}/drop`, { method: "POST" }, []);
}

export async function approveContentReady(sourceId: string) {
  return run<{ approved: number }>(`/org/content/sources/${sourceId}/approve-ready`, { method: "POST" }, [`/content/${sourceId}`]);
}

export async function scheduleContent(sourceId?: string) {
  return run<{ scheduled: number }>("/org/content/schedule", { method: "POST", body: { source_id: sourceId ?? null } }, ["/content", "/content/calendar"]);
}

export async function moveContentPost(id: string, scheduledAt: string | null) {
  return run<{ id: string }>(`/org/content/posts/${id}/slot`, { method: "PATCH", body: { scheduled_at: scheduledAt } }, ["/content/calendar"]);
}

export async function newBackground(momentId: string) {
  return run<{ path: string; redrawn: number }>(`/org/content/moments/${momentId}/background`, { method: "POST" }, ["/content"]);
}

export async function saveBrandKit(changes: Record<string, unknown>) {
  return run<{ saved: string[]; images_redrawn: number }>("/org/content/brand", { method: "PUT", body: changes }, ["/content/brand"]);
}

export async function uploadBrandLogo(form: FormData) {
  return upload<{ images_redrawn: number }>("/org/content/brand/logo", form, ["/content/brand"]);
}

export async function learnBrandVoice(posts: string) {
  return run<{ learned: boolean; samples: number; voice?: string; reason?: string }>("/org/content/brand/voice", { method: "POST", body: { posts } }, ["/content/brand"]);
}

// ---------- Telegram ----------

export async function connectTelegram(botToken: string) {
  return run<{ username: string; link: string; delivery: string }>("/org/connections/telegram", { method: "POST", body: { bot_token: botToken } },
    ["/settings/connections", "/automations", "/onboarding"]);
}

export async function telegramLinkUrl() {
  return run<{ url: string; expires_in_minutes: number }>("/org/telegram/link", { method: "POST" }, []);
}

export async function unlinkTelegram() {
  return run<{ linked: boolean }>("/org/telegram", { method: "DELETE" }, ["/settings/account"]);
}

// ---------- Notification Center ----------

export type InboxItem = { id: number; event_type: string; title: string; body: string; link: string | null; status: string; critical: boolean;
                          created_at: string; read_at: string | null };

export async function getInbox() {
  return run<{ items: InboxItem[]; unread: number }>("/org/notifications/inbox?limit=20", { method: "GET" }, []);
}

export async function markInboxRead(ids?: number[]) {
  return run<{ read: number }>("/org/notifications/inbox/read", { method: "POST", body: { ids: ids ?? null } }, []);
}

export type RuleIn = { name: string; event_type: string; conditions: { field: string; op: string; value: string | number }[]; roles: string[];
                       user_ids: string[]; assignee: boolean; channels: string[]; cadence: "now" | "digest"; digest_hour: number; critical: boolean;
                       personal: boolean };

export async function saveRule(rule: RuleIn, id?: string) {
  return run<{ id: string }>(id ? `/org/notification-rules/${id}` : "/org/notification-rules", { method: id ? "PUT" : "POST", body: rule },
    ["/settings/notifications"]);
}

export async function ruleAction(id: string, action: "enable" | "disable" | "mute" | "unmute" | "delete" | "test") {
  if (action === "delete") return run<unknown>(`/org/notification-rules/${id}`, { method: "DELETE" }, ["/settings/notifications"]);
  if (action === "test") return run<{ results: Record<string, string> }>(`/org/notification-rules/${id}/test`, { method: "POST" }, []);
  if (action === "enable" || action === "disable")
    return run<unknown>(`/org/notification-rules/${id}/enabled`, { method: "POST", body: { enabled: action === "enable" } }, ["/settings/notifications"]);
  return run<unknown>(`/org/notification-rules/${id}/mute`, { method: "POST", body: { muted: action === "mute" } }, ["/settings/notifications"]);
}

export async function saveNotificationSettings(quietFrom: string | null, quietTo: string | null, maxPerHour: number) {
  return run<unknown>("/org/notification-settings", { method: "PUT", body: { quiet_from: quietFrom, quiet_to: quietTo, max_per_hour: maxPerHour } },
    ["/settings/notifications"]);
}

// ---------- Business Pulse ----------

export async function savePulseSettings(enabled: boolean, hour: number, weekly: boolean) {
  return run<unknown>("/org/pulse/settings", { method: "PUT", body: { enabled, hour, weekly } }, ["/home"]);
}

export async function sendPulseNow() {
  return run<{ event_id: number }>("/org/pulse/send-now", { method: "POST" }, []);
}

// ---------- governance ----------

export async function saveAutonomy(action: string, level: string, maxPerDay: number | null, quietHours: boolean) {
  return run<unknown>(`/org/governance/${action}`, { method: "PUT", body: { level, max_per_day: maxPerDay, quiet_hours: quietHours } },
    ["/settings/autonomy"]);
}

// ---------- calendar & appointment concierge (9.3) ----------

export async function markBooking(id: string, status: "showed" | "no_show" | "cancelled" | "confirmed") {
  return run<{ status: string }>(`/org/bookings/${id}/status`, { method: "POST", body: { status } }, ["/calendar"]);
}

export async function addToWaitlist(entry: { name: string; phone?: string; email?: string; service_key: string; notes?: string }) {
  return run<{ id: string }>("/org/waitlist", { method: "POST", body: entry }, ["/calendar"]);
}

export async function removeFromWaitlist(id: string) {
  return run<{ removed: boolean }>(`/org/waitlist/${id}`, { method: "DELETE" }, ["/calendar"]);
}

export async function researchLead(id: string) {
  return run<{ status: string }>(`/org/leads/${id}/research`, { method: "POST" }, [`/leads/${id}`, "/leads"]);
}

// ---------- bookkeeping (9.5) ----------

export async function uploadDocument(form: FormData) {
  return upload<{ id: string; status: string; error: string | null }>("/org/bookkeeping/documents", form, ["/bookkeeping"]);
}

export async function trySampleDocuments() {
  return run<{ items: { id: string; status: string }[] }>("/org/bookkeeping/samples", { method: "POST" }, ["/bookkeeping"]);
}

export async function reviewDocument(id: string, action: "accept" | "reject", fields?: Record<string, unknown>) {
  return run<{ status: string }>(`/org/bookkeeping/documents/${id}`, { method: "PUT", body: { action, fields } }, ["/bookkeeping", `/bookkeeping/${id}`, "/needs-you"]);
}

export async function startInstagram() {
  return run<{ url: string }>("/org/connections/instagram/start", { method: "POST" });
}

// ---------- reviews (9.2) and competitor & price watch (10.1) ----------

export async function syncReviews() {
  return run<{ new: number }>("/org/reviews/sync", { method: "POST" }, ["/reviews"]);
}

export async function replyToReview(id: string, action: "post" | "skip", body?: string) {
  return run<{ status: string }>(`/org/reviews/${id}`, { method: "PUT", body: { action, body } }, ["/reviews", "/needs-you"]);
}

export async function addWatcher(w: { kind: "page" | "price"; name: string; url: string }) {
  return run<{ id: string; error: string | null }>("/org/watchers", { method: "POST", body: w }, ["/watch"]);
}

export async function checkWatcher(id: string) {
  return run<{ changed: boolean; summary?: string; error?: string }>(`/org/watchers/${id}/check`, { method: "POST" }, ["/watch"]);
}

export async function setWatcherStatus(id: string, status: "active" | "paused") {
  return run<{ status: string }>(`/org/watchers/${id}`, { method: "PUT", body: { status } }, ["/watch"]);
}

export async function removeWatcher(id: string) {
  return run<{ removed: boolean }>(`/org/watchers/${id}`, { method: "DELETE" }, ["/watch"]);
}

export async function startGoogleSheets() {
  return run<{ url: string }>("/org/connections/google-sheets/start", { method: "POST" });
}

// ---------- Ask your business + MCP tokens ----------

export async function askBusiness(question: string, history: { role: "user" | "assistant"; content: string }[]) {
  return run<{ answer: string; tools: string[]; plan?: { id: string; steps: string[] } }>("/org/ask", { method: "POST", body: { question, history } });
}

export async function runCopilotPlan(id: string) {
  return run<{ results: { summary: string; ok: boolean; result: string }[] }>(`/org/copilot/plans/${id}/run`, { method: "POST" }, ["/needs-you", "/calendar", "/invoices"]);
}
export async function cancelCopilotPlan(id: string) {
  return run<unknown>(`/org/copilot/plans/${id}/cancel`, { method: "POST" });
}

export async function createApiToken(name: string) {
  return run<{ id: string; token: string; mcp_url: string }>("/org/api-tokens", { method: "POST", body: { name } }, ["/ask"]);
}

export async function revokeApiToken(id: string) {
  return run<{ revoked: boolean }>(`/org/api-tokens/${id}`, { method: "DELETE" }, ["/ask"]);
}

export async function requestLongform(sourceId: string) {
  return run<{ status: string }>(`/org/content/sources/${sourceId}/longform`, { method: "POST", body: {} }, [`/content/${sourceId}`]);
}

export async function cutContentClips(sourceId: string) {
  return run<{ status: string; moments: number }>(`/org/content/sources/${sourceId}/clips`, { method: "POST" }, [`/content/${sourceId}`]);
}

export async function saveLongform(id: string, sourceId: string, v: { title: string; summary: string | null; body: string; approve: boolean }) {
  return run<{ status: string; problems: string[] }>(`/org/content/longform/${id}`, { method: "PUT", body: v }, [`/content/${sourceId}`]);
}

export async function startLinkedIn() {
  return run<{ url: string }>("/org/connections/linkedin/start", { method: "POST" });
}

// ---------- CA Firm pack (docs/PACKS.md) ----------

const CA = ["/filings", "/ca-clients", "/compliance", "/needs-you"];
const caPaths = (cid?: string) => (cid ? [...CA, `/ca-clients/${cid}`] : CA);

export async function caSaveClient(body: Record<string, unknown>, cid?: string) {
  return run<{ id: string }>(cid ? `/org/ca/clients/${cid}` : "/org/ca/clients", { method: cid ? "PATCH" : "POST", body }, caPaths(cid));
}
export async function caDeleteClient(cid: string) {
  return run<{ deleted: boolean }>(`/org/ca/clients/${cid}`, { method: "DELETE" }, CA);
}
export async function caImportClients(form: FormData) {
  return upload<{ added: number; updated: number; errors: string[] }>("/org/ca/clients/import", form, CA);
}
export async function caAddFiling(body: Record<string, unknown>) {
  return run<{ id: string }>("/org/ca/filings", { method: "POST", body }, caPaths(String(body.client_id ?? "")));
}
export async function caEditFiling(fid: string, body: Record<string, unknown>, cid?: string) {
  return run<{ status: string }>(`/org/ca/filings/${fid}`, { method: "PATCH", body }, caPaths(cid));
}
export async function caDeleteFiling(fid: string, cid?: string) {
  return run<{ deleted: boolean }>(`/org/ca/filings/${fid}`, { method: "DELETE" }, caPaths(cid));
}
export async function caSeason(body: Record<string, unknown>) {
  return run<{ created: number; already_there: number }>("/org/ca/filings/season", { method: "POST", body }, CA);
}
export async function caChecklist(fid: string, body: { key: string; status: string; label?: string }, cid?: string) {
  return run<{ complete: boolean }>(`/org/ca/filings/${fid}/checklist`, { method: "POST", body }, caPaths(cid));
}
export async function caRebuildChecklist(fid: string, cid?: string) {
  return run<unknown>(`/org/ca/filings/${fid}/checklist/rebuild`, { method: "POST" }, caPaths(cid));
}
export async function caPauseChase(fid: string, paused: boolean, cid?: string) {
  return run<unknown>(`/org/ca/filings/${fid}/chase`, { method: "POST", body: { paused } }, caPaths(cid));
}
export async function caUploadFile(cid: string, form: FormData) {
  return upload<{ file_id: string; label?: string; item?: string | null; still_missing?: string[] }>(`/org/ca/clients/${cid}/files`, form, caPaths(cid));
}
export async function caDeleteFile(fid: string, cid: string) {
  return run<unknown>(`/org/ca/files/${fid}`, { method: "DELETE" }, caPaths(cid));
}
export async function caReadFile(fid: string, cid: string) {
  return run<unknown>(`/org/ca/files/${fid}/read`, { method: "POST" }, caPaths(cid));
}
export async function caTrySamples(cid: string) {
  return run<unknown>(`/org/ca/clients/${cid}/samples`, { method: "POST" }, caPaths(cid));
}
export async function caRefreshCalendar() {
  return run<{ created: number }>("/org/ca/compliance/refresh", { method: "POST" }, CA);
}

/** Check the official sources for due-date changes now (a check from the last hour is reused). */
export async function msmeSettings(body: { enabled: boolean; udyam: string | null; category: string; activity: string }) {
  return run<unknown>("/org/invoices/msme", { method: "PUT", body }, ["/invoices"]);
}

export async function msmeCustomer(cid: string, body: { credit_days?: number | null; business_buyer?: boolean | null }) {
  return run<unknown>(`/org/invoices/msme/customers/${cid}`, { method: "PUT", body }, ["/invoices"]);
}

export async function caPortalSettings(body: { enabled: boolean; title?: string; color?: string; logo_url?: string; welcome?: string }) {
  return run<{ enabled: boolean }>("/org/ca/portal", { method: "PUT", body }, ["/ca-clients"]);
}

export async function caPortalLink(cid: string, send: boolean) {
  return run<{ url: string; sent?: string; channel?: string }>(`/org/ca/clients/${cid}/portal${send ? "?send=true" : ""}`, { method: "POST" }, [`/ca-clients/${cid}`]);
}

export async function caPortalRevoke(cid: string) {
  return run<{ revoked: number }>(`/org/ca/clients/${cid}/portal`, { method: "DELETE" }, [`/ca-clients/${cid}`]);
}

export async function caCheckDueDates() {
  return run<{ id: string; status: string; reused: boolean }>("/org/ca/compliance/updates/check", { method: "POST" }, ["/compliance"]);
}

/** Agentry HQ → Due dates. */
export async function hqDueDatesCheck() {
  return run<{ id: string; status: string; reused: boolean }>("/hq/due-dates/check", { method: "POST" }, ["/hq/due-dates"]);
}

export async function hqDueDateDecide(id: string, action: "approve" | "reject" | "withdraw") {
  return run<{ status: string; cards: number }>(`/hq/due-dates/${id}/${action}`, { method: "POST" }, ["/hq/due-dates", "/compliance"]);
}

export async function testMissedCall(phone: string) {
  return run<{ recorded: boolean; reason?: string }>("/org/missed-calls/test", { method: "POST", body: { phone } }, ["/missed-calls"]);
}

export async function hqResendSignup(id: string) {
  return run<{ ok: boolean }>(`/hq/signups/${id}/resend`, { method: "POST" }, ["/hq"]);
}

export async function hqRuleDecide(id: string, action: "approve" | "reject" | "withdraw") {
  return run<{ status: string }>(`/hq/due-dates/rules/${id}/${action}`, { method: "POST" }, ["/hq/due-dates", "/compliance"]);
}

export async function hqRuleAdd(body: Record<string, string>) {
  return run<{ status: string }>("/hq/due-dates/rules", { method: "POST", body }, ["/hq/due-dates", "/compliance"]);
}

export async function hqDueDateAdd(body: Record<string, string>) {
  return run<{ status: string; cards: number }>("/hq/due-dates", { method: "POST", body }, ["/hq/due-dates", "/compliance"]);
}

export async function caTool(path: string, form: FormData | null, cid?: string) {
  // path: "/org/ca/clients/{cid}/gst", ".../bank/sample", "/org/ca/excel/table"…
  if (!/^\/org\/ca\/(clients\/[0-9a-f-]{36}\/(gst|capital-gains|bank|notices|tds|audit|anomalies|hub|gstr1|financials|depreciation)(\/sample)?|excel\/(table|reconcile|ask|(clean|anomalies)(\/sample)?))$/.test(path)) {
    return { ok: false as const, error: "unknown tool" };
  }
  const paths = [...caPaths(cid), "/excel"];
  return form ? upload<{ id?: string; work_id?: string }>(path, form, paths) : run<{ id?: string; work_id?: string }>(path, { method: "POST" }, paths);
}
export async function caItr(cid: string, body: Record<string, unknown>) {
  return run<{ id: string }>(`/org/ca/clients/${cid}/itr`, { method: "POST", body }, caPaths(cid));
}
export async function caBankLine(wid: string, body: { row: number; category: string; learn: boolean }) {
  return run<{ learned: string | null }>(`/org/ca/work/${wid}/bank-line`, { method: "POST", body }, [`/ca-work/${wid}`]);
}
export async function caLedgerLine(wid: string, body: { ledger: string; line: string; learn: boolean }) {
  return run<{ summary: unknown; balanced: boolean }>(`/org/ca/work/${wid}/ledger`, { method: "POST", body }, [`/ca-work/${wid}`]);
}
export async function caTaxOpening(wid: string, opening: Record<string, number>) {
  return run<{ summary: unknown }>(`/org/ca/work/${wid}/tax-opening`, { method: "POST", body: { opening } }, [`/ca-work/${wid}`]);
}
export async function caDeleteWork(wid: string, cid?: string) {
  return run<unknown>(`/org/ca/work/${wid}`, { method: "DELETE" }, [...caPaths(cid), "/excel"]);
}
export async function caSaveRecurring(body: Record<string, unknown>, rid?: string) {
  return run<{ id: string }>(rid ? `/org/ca/recurring/${rid}` : "/org/ca/recurring", { method: rid ? "PATCH" : "POST", body }, ["/recurring"]);
}
export async function caDeleteRecurring(rid: string) {
  return run<unknown>(`/org/ca/recurring/${rid}`, { method: "DELETE" }, ["/recurring"]);
}
export async function caBookRecurring() {
  return run<{ booked: number }>("/org/ca/recurring/run", { method: "POST" }, ["/recurring", "/bookkeeping"]);
}

// ---------- AI video studio ----------

const VID = (id?: string) => ["/videos", "/needs-you", ...(id ? [`/videos/${id}`] : [])];
export async function makeVideo(topic: string | null) {
  return run<{ id: string }>("/org/videos", { method: "POST", body: { topic: topic || null } }, VID());
}
export async function editVideo(id: string, body: Record<string, unknown>) {
  return run<unknown>(`/org/videos/${id}`, { method: "PATCH", body }, VID(id));
}
export async function generateVideo(id: string) {
  return run<unknown>(`/org/videos/${id}/generate`, { method: "POST" }, VID(id));
}
export async function replanVideo(id: string) {
  return run<unknown>(`/org/videos/${id}/replan`, { method: "POST" }, VID(id));
}
export async function publishVideo(id: string) {
  return run<{ url: string }>(`/org/videos/${id}/publish`, { method: "POST" }, VID(id));
}
export async function rejectVideo(id: string) {
  return run<unknown>(`/org/videos/${id}/reject`, { method: "POST" }, VID(id));
}
export async function startYouTube() {
  return run<{ url: string }>("/org/connections/youtube/start", { method: "POST" });
}

// ---------- support desk (ROADMAP-V3 A2) ----------

export async function editTicket(id: string, body: Record<string, unknown>) {
  return run<{ status: string }>(`/org/tickets/${id}`, { method: "PATCH", body }, ["/tickets", `/tickets/${id}`]);
}
export async function newTicket(body: Record<string, unknown>) {
  return run<{ id: string; number: number }>("/org/tickets", { method: "POST", body }, ["/tickets"]);
}
export async function importOrders(form: FormData) {
  return upload<{ imported: number }>("/org/tickets/orders/import", form, ["/tickets"]);
}

// ---------- catalogue & quotes (ROADMAP-V3 A3) ----------

export async function importProducts(form: FormData) {
  return upload<{ imported: number; skipped_rows: number[] }>("/org/quotes/products/import", form, ["/quotes"]);
}
export async function createQuote(body: Record<string, unknown>) {
  return run<{ id: string; number: string; total: number }>("/org/quotes", { method: "POST", body }, ["/quotes"]);
}
export async function sendQuote(id: string) {
  return run<{ status: string }>(`/org/quotes/${id}/send`, { method: "POST" }, ["/quotes"]);
}
export async function quoteOutcome(id: string, outcome: "won" | "lost") {
  return run<unknown>(`/org/quotes/${id}/outcome`, { method: "POST", body: { outcome } }, ["/quotes"]);
}

// ---------- renewals (ROADMAP-V3 A4) ----------

export async function importRenewals(form: FormData) {
  return upload<{ added: number; skipped_rows: number[] }>("/org/renewals/import", form, ["/renewals"]);
}
export async function addRenewal(body: Record<string, unknown>) {
  return run<{ id: string }>("/org/renewals", { method: "POST", body }, ["/renewals"]);
}
export async function markRenewal(id: string, action: "renewed" | "cancelled") {
  return run<unknown>(`/org/renewals/${id}/mark`, { method: "POST", body: { action } }, ["/renewals"]);
}

// ---------- hiring (ROADMAP-V3 A5) ----------

export async function createJob(body: Record<string, unknown>) {
  return run<{ id: string }>("/org/hiring/jobs", { method: "POST", body }, ["/hiring"]);
}
export async function jobStatus(id: string, status: string) {
  return run<unknown>(`/org/hiring/jobs/${id}`, { method: "PATCH", body: { status } }, ["/hiring", `/hiring/${id}`]);
}
export async function uploadCvs(jobId: string, form: FormData) {
  return upload<{ added: { id: string; name: string | null; score: number; verdict: string }[]; errors: string[] }>(`/org/hiring/jobs/${jobId}/candidates`, form, [`/hiring/${jobId}`]);
}
export async function candidateStage(id: string, body: { status: string; interview_at?: string | null }, jobId: string) {
  return run<{ message: string | null }>(`/org/hiring/candidates/${id}/stage`, { method: "POST", body }, [`/hiring/${jobId}`]);
}
export async function writeScript(topic: string | null) {
  return run<{ id: string }>("/org/videos/scripts", { method: "POST", body: { topic: topic || null } }, ["/videos"]);
}
export async function scriptToVideo(id: string) {
  return run<{ id: string }>(`/org/videos/scripts/${id}/make`, { method: "POST" }, ["/videos"]);
}
export async function scriptStatus(id: string, status: string) {
  return run<unknown>(`/org/videos/scripts/${id}`, { method: "PATCH", body: { status } }, ["/videos"]);
}

// ---------- local SEO (ROADMAP-V3 B1) ----------

export async function runSeoAudit(url: string | null) {
  return run<{ score: number }>("/org/seo/audit", { method: "POST", body: { url: url || null } }, ["/seo"]);
}
export async function writeSeoArticle(topic: string) {
  return run<{ id: string }>("/org/seo/articles", { method: "POST", body: { topic } }, ["/seo"]);
}
export async function editSeoArticle(id: string, body: Record<string, unknown>) {
  return run<unknown>(`/org/seo/articles/${id}`, { method: "PATCH", body }, ["/seo", `/seo/${id}`]);
}

// ---------- stock shelf scanner (ROADMAP-V3 B2) ----------

export async function scanShelf(form: FormData) {
  return upload<{ id: string; items: { name: string; read_as: string; count: number; unit: string; confidence: number; item_id: string | null; previous: number | null }[] }>(
    "/org/stock/scan", form, ["/stock"]);
}
export async function applyScan(id: string, counts: unknown[], addNew: boolean) {
  return run<{ updated: number; added: number }>(`/org/stock/scans/${id}/apply`, { method: "POST", body: { counts, add_new: addNew } }, ["/stock"]);
}
export async function importStock(form: FormData) {
  return upload<{ imported: number }>("/org/stock/items/import", form, ["/stock"]);
}

// ---------- festival campaigns (ROADMAP-V3 B3) ----------

export async function planFestival(festival: string, on_date: string) {
  return run<{ id: string | null }>("/org/festivals/plans", { method: "POST", body: { festival, on_date } }, ["/festivals"]);
}
export async function festivalStatus(id: string, status: string) {
  return run<unknown>(`/org/festivals/plans/${id}`, { method: "PATCH", body: { status } }, ["/festivals"]);
}

// ---------- SOP & proposal drafter (ROADMAP-V3 B4) ----------

export async function draftDoc(kind: string, brief: string) {
  return run<{ id: string }>("/org/docs", { method: "POST", body: { kind, brief } }, ["/docs"]);
}
export async function editDoc(id: string, body: Record<string, unknown>) {
  return run<unknown>(`/org/docs/${id}`, { method: "PATCH", body }, ["/docs", `/docs/${id}`]);
}

// ---------- ops dispatcher (ROADMAP-V3 C2) ----------

export async function newJob(body: Record<string, unknown>) {
  return run<{ id: string; number: number; technician: string | null }>("/org/dispatch/jobs", { method: "POST", body }, ["/jobs"]);
}
export async function editJob(id: string, body: Record<string, unknown>) {
  return run<{ status: string; told: string | null }>(`/org/dispatch/jobs/${id}`, { method: "PATCH", body }, ["/jobs"]);
}
export async function jobPhoto(id: string, form: FormData) {
  return upload<{ path: string }>(`/org/dispatch/jobs/${id}/photos`, form, ["/jobs"]);
}
export async function addTechnician(body: Record<string, unknown>) {
  return run<{ id: string }>("/org/dispatch/technicians", { method: "POST", body }, ["/jobs"]);
}

// ---------- AI visibility ----------
export async function saveVisibilitySetup(body: Record<string, unknown>) {
  return run<{ missing: string | null }>("/org/ai-visibility/setup", { method: "PUT", body }, ["/ai-visibility"]);
}
export async function checkVisibilityNow() {
  return run<{ run_id: string }>("/org/ai-visibility/check", { method: "POST", body: {} }, ["/ai-visibility"]);
}
export async function writeAnswerPage(question: string) {
  return run<{ id: string }>("/org/ai-visibility/write-page", { method: "POST", body: { question } }, ["/ai-visibility", "/seo"]);
}

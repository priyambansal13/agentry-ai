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
};

export async function hqCreateClient(input: NewClientInput): Promise<ActionResult<{ orgId: string; invite: string | null }>> {
  const me = await getMe();
  if (!me.is_staff) return { ok: false, error: "Agentry staff only" };
  if (input.name.trim().length < 2) return { ok: false, error: "Enter the business name" };
  if (!input.automations.length) return { ok: false, error: "Choose at least one automation" };
  const org = await createOrganization(input.name.trim());
  const res = await hq<{ org_id: string }>("/hq/clients", { method: "POST", body: {
    org_id: org.id, country: input.country, timezone: input.timezone, currency: input.currency,
    website: input.website.trim() || null, automations: input.automations, plan: input.plan,
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

/** Auto-compact numbers for stat tiles: 1,284 / 12.9K / ₹3.1L / $4.2M. */
export function formatMetric(value: number, unit: string, currency?: string | null): string {
  if (unit === "currency" && currency) {
    if (currency === "INR") {
      if (value >= 1e7) return `₹${(value / 1e7).toFixed(1)}Cr`;
      if (value >= 1e5) return `₹${(value / 1e5).toFixed(1)}L`;
      return `₹${Math.round(value).toLocaleString("en-IN")}`;
    }
    return new Intl.NumberFormat("en-US", { style: "currency", currency, notation: "compact", maximumFractionDigits: 1 }).format(value);
  }
  return new Intl.NumberFormat("en-US", { notation: value >= 10000 ? "compact" : "standard", maximumFractionDigits: 1 }).format(value);
}

export function formatDateTime(iso: string): string {
  return new Date(iso).toLocaleString("en-IN", { dateStyle: "medium", timeStyle: "short" });
}

export const automationNames: Record<string, string> = {
  inbox_triage: "Inbox triage",
  invoice_follow_up: "Invoice follow-up",
  website_chat: "Website chat agent",
  ai_receptionist: "AI receptionist",
  lead_reactivation: "Lead reactivation",
  speed_to_lead: "Speed-to-lead",
  cold_email: "Personal cold email",
  content_repurposing: "Content repurposing",
  whatsapp_assistant: "WhatsApp assistant",
};

export const statusLabels: Record<string, { label: string; tone: "success" | "warning" | "neutral" | "danger" | "lime" }> = {
  live: { label: "Live", tone: "success" },
  approval_mode: { label: "Approval mode", tone: "lime" },
  setup: { label: "Setting up", tone: "neutral" },
  paused: { label: "Paused", tone: "warning" },
  error: { label: "Needs attention", tone: "danger" },
  onboarding: { label: "Onboarding", tone: "lime" },
  pending_setup: { label: "Pending setup", tone: "neutral" },
};

export const approvalKinds: Record<string, string> = {
  reply_draft: "Reply to approve",
  outbound_draft: "Message to approve",
  payment_review: "Check a payment",
  handoff: "Asked for a person",
  callback: "Call back",
  escalation: "Escalation",
  dispute: "Dispute",
  low_confidence: "Not sure",
};

export const categoryTone: Record<string, "danger" | "lime" | "success" | "warning" | "neutral"> = {
  Urgent: "danger", Client: "success", Lead: "lime", "Invoice/Payment": "warning",
  Promotion: "neutral", Newsletter: "neutral", Spam: "neutral", Other: "neutral",
};

export function timeAgo(iso: string): string {
  const s = (Date.now() - new Date(iso).getTime()) / 1000;
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.floor(s / 60)} min ago`;
  if (s < 86400) return `${Math.floor(s / 3600)} h ago`;
  return new Date(iso).toLocaleDateString("en-IN", { day: "numeric", month: "short" });
}

// Agentry's own sales pipeline (HQ → demo requests)
export const DEMO_STATUS: Record<string, { label: string; tone: "lime" | "neutral" | "success" | "warning" | "danger" }> = {
  new: { label: "New", tone: "lime" }, demo_built: { label: "Demo built", tone: "neutral" }, demo_sent: { label: "Demo sent", tone: "warning" },
  in_talks: { label: "In talks", tone: "success" }, won: { label: "Won", tone: "success" }, lost: { label: "Lost", tone: "neutral" },
};

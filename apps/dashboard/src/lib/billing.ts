export type Line = {
  id: string; position: number; kind: string; description: string; quantity: number; unit_price: number; amount: number;
  evidence: string[]; disputed: boolean; dispute_reason: string | null; dispute_resolution: "accepted" | "rejected" | "partial" | null;
};
export type Statement = {
  id: string; number: string; period_start: string; period_end: string; currency: string; status: string; subtotal: number;
  tax: number; total: number; issued_at: string | null; dispute_until: string | null; paid_at: string | null; payment_link: string | null;
  results: { appointments?: number; recovered?: number; messages?: number; emails_triaged?: number };
};
export type Outcome = { id: string; kind: string; occurred_at: string; value: number; strength: string; evidence: Record<string, unknown>;
  call?: { conversation_id: string; duration_seconds: number | null; summary: string | null; recording: boolean } | null };
export type StatementDetail = {
  statement: Statement; lines: Line[]; evidence: Record<string, Outcome>; client: { name: string; country: string };
  excluded: { kind: string; occurred_at: string; value: number; exclusion_reason: string; evidence: Record<string, unknown> }[];
};

export function money(v: number | string, currency: string): string {
  const n = Number(v);
  const abs = currency === "INR"
    ? `₹${Math.abs(n).toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
    : new Intl.NumberFormat("en-US", { style: "currency", currency }).format(Math.abs(n));
  return n < 0 ? `−${abs}` : abs;
}

export const STATUS_TONE: Record<string, "success" | "lime" | "warning" | "neutral" | "danger"> = {
  paid: "success", finalized: "lime", issued: "warning", draft: "neutral", void: "neutral",
};

export function period(s: Statement) {
  return new Date(s.period_start).toLocaleDateString("en-IN", { month: "long", year: "numeric" });
}

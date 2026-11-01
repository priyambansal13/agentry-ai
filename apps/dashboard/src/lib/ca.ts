/** Shared by the CA desk's server pages and client components (docs/PACKS.md). */
export const STATUS_TONE: Record<string, "neutral" | "warning" | "success" | "danger"> = {
  docs_pending: "warning", in_prep: "neutral", review: "neutral", filed: "success", verified: "success" };

export const day = (d: string | null) =>
  d ? new Date(`${d}T12:00:00Z`).toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric", timeZone: "UTC" }) : "";

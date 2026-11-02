/** AI video studio: shared by server pages and client components. */
export const VIDEO_STATUS: Record<string, [string, "neutral" | "warning" | "success" | "danger" | "lime"]> = {
  planning: ["Planning", "neutral"], needs_attention: ["Needs a look", "warning"], generating: ["Generating", "neutral"], composing: ["Putting together", "neutral"],
  review: ["To approve", "lime"], publishing: ["Publishing", "neutral"], published: ["Published", "success"], rejected: ["Rejected", "neutral"],
  failed: ["Failed", "danger"], skipped: ["Skipped", "warning"] };
export const WORKING = ["planning", "generating", "composing", "publishing"];

import type { CaMeta } from "@/components/ca";

/** The CA agents that work on one client's documents (ITR, capital gains, bank statements, notices, TDS, 3CD). */
export async function CaTools({ clientId, meta }: { clientId: string; meta: CaMeta }) {
  void clientId;
  void meta;
  return null;
}

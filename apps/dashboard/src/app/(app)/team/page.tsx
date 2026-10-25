import { redirect } from "next/navigation";
import { TeamManager } from "@/components/team-manager";
import { listTeam } from "@/lib/clients";
import { can } from "@/lib/permissions";
import { getActiveOrg, getMe } from "@/lib/session";

export const metadata = { title: "Team" };

export default async function TeamPage() {
  const [me, active] = await Promise.all([getMe(), getActiveOrg()]);
  if (!active) redirect("/home");
  const allowed = (r: string, a: string) => me.is_staff || can(active.role, r, a);
  const team = await listTeam(active.id);
  return (
    <div className="space-y-6">
      <header>
        <h1 className="font-display text-3xl font-bold tracking-tight">Team</h1>
        <p className="mt-1 text-muted">Who can sign in to {active.name}, and what they can do.</p>
      </header>
      <TeamManager members={team.members} invitations={allowed("invitation", "create") ? team.invitations : []} me={me.user.email}
        canInvite={allowed("invitation", "create")} canChange={allowed("member", "update")} canRemove={allowed("member", "delete")}
        canCancel={allowed("invitation", "cancel")} />
    </div>
  );
}

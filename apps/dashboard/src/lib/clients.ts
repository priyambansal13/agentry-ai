import "server-only";
import { randomUUID } from "node:crypto";
import { authPool } from "./auth";
import { sendMail } from "./mail";

/** Organisations and invitations live in Better Auth's schema, which only the dashboard writes. */

export function slugify(name: string): string {
  return name.toLowerCase().normalize("NFKD").replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "").slice(0, 40) || "client";
}

export async function createOrganization(name: string): Promise<{ id: string; slug: string }> {
  const base = slugify(name);
  for (let i = 0; i < 5; i++) {
    const slug = i === 0 ? base : `${base}-${randomUUID().slice(0, 4)}`;
    const id = randomUUID();
    const r = await authPool.query(`insert into organization (id, name, slug, "createdAt") values ($1, $2, $3, now())
                                    on conflict (slug) do nothing returning id`, [id, name, slug]);
    if (r.rowCount) return { id, slug };
  }
  throw new Error("couldn't find a free web address for this name");
}

export async function deleteOrganization(id: string): Promise<void> {
  await authPool.query(`delete from invitation where "organizationId" = $1`, [id]);
  await authPool.query(`delete from member where "organizationId" = $1`, [id]);
  await authPool.query(`delete from organization where id = $1`, [id]);
}

/** Invite someone to a client organisation. An existing Agentry user is added straight away (and told by email);
 *  anyone else gets the standard 7-day invitation link, which also works for people who have never signed in. */
export async function inviteToOrganization(o: { orgId: string; orgName: string; email: string; name?: string; role: string;
                                                inviterId: string; inviterName: string }): Promise<"added" | "invited"> {
  const email = o.email.trim().toLowerCase();
  const base = process.env.BETTER_AUTH_URL ?? "http://localhost:3201";
  const existing = (await authPool.query<{ id: string; emailVerified: boolean; name: string }>(
    `select id, "emailVerified", name from "user" where lower(email) = $1`, [email])).rows[0];
  // Someone who has signed in before is added straight away. Anyone else gets an invitation; we create their (not yet
  // verified) account now so it carries the name we were given: a magic-link sign-in then lands on a named user.
  const user = existing?.emailVerified ? existing : null;
  if (!existing && o.name?.trim()) {
    await authPool.query(`insert into "user" (id, name, email, "emailVerified", role, "createdAt", "updatedAt")
      values ($1, $2, $3, false, 'user', now(), now()) on conflict (email) do nothing`, [randomUUID(), o.name.trim(), email]);
  } else if (existing && !existing.name && o.name?.trim()) {
    await authPool.query(`update "user" set name = $1 where id = $2`, [o.name.trim(), existing.id]);
  }
  if (user) {
    await authPool.query(`insert into member (id, "organizationId", "userId", role, "createdAt")
      select $1, $2, $3, $4, now() where not exists (select 1 from member where "organizationId" = $2 and "userId" = $3)`,
      [randomUUID(), o.orgId, user.id, o.role]);
    await sendMail(email, `You now have access to ${o.orgName} on Agentry`,
      `${o.inviterName} gave you access to ${o.orgName} on Agentry as ${o.role}.\n\nSign in: ${base}/sign-in`);
    return "added";
  }
  await authPool.query(`update invitation set status = 'canceled' where "organizationId" = $1 and lower(email) = $2 and status = 'pending'`,
                       [o.orgId, email]);
  const id = randomUUID();
  await authPool.query(`insert into invitation (id, "organizationId", email, role, status, "expiresAt", "createdAt", "inviterId")
    values ($1, $2, $3, $4, 'pending', now() + interval '7 days', now(), $5)`, [id, o.orgId, email, o.role, o.inviterId]);
  await sendMail(email, `${o.inviterName} invited you to ${o.orgName} on Agentry`,
    `${o.name ? `Hi ${o.name},\n\n` : ""}${o.inviterName} invited you to ${o.orgName} on Agentry as ${o.role}.\n\n` +
    `Join here (one click signs you in; you can set a password after): ${base}/invite/${id}\n\n` +
    `This link is just for you. It expires in 7 days, or as soon as you've joined.`);
  return "invited";
}

export async function pendingInvitations(orgId: string) {
  return (await authPool.query<{ email: string; role: string; expiresAt: string }>(
    `select email, role, "expiresAt" from invitation where "organizationId" = $1 and status = 'pending' and "expiresAt" > now()
     order by "createdAt" desc`, [orgId])).rows;
}

export type TeamMember = { id: string; userId: string; name: string; email: string; role: string; joined: string };
export type PendingInvite = { id: string; email: string; role: string; expiresAt: string };

export async function listTeam(orgId: string): Promise<{ members: TeamMember[]; invitations: PendingInvite[] }> {
  const [m, i] = await Promise.all([
    authPool.query<TeamMember>(`select m.id, m."userId", u.name, u.email, m.role, m."createdAt" as joined from member m
      join "user" u on u.id = m."userId" where m."organizationId" = $1 order by m."createdAt"`, [orgId]),
    authPool.query<PendingInvite>(`select id, email, role, "expiresAt" from invitation where "organizationId" = $1
      and status = 'pending' and "expiresAt" > now() order by "createdAt" desc`, [orgId]),
  ]);
  return { members: m.rows, invitations: i.rows };
}

/** Change a member's role or remove them. Refuses to leave a business without an owner. */
export async function updateMember(orgId: string, memberId: string, change: { role: string } | "remove"): Promise<{ email: string }> {
  const target = (await authPool.query<{ role: string; email: string }>(`select m.role, u.email from member m join "user" u on u.id = m."userId"
    where m.id = $1 and m."organizationId" = $2`, [memberId, orgId])).rows[0];
  if (!target) throw new Error("This person isn't on the team");
  const losesOwner = target.role.split(",").includes("owner") && (change === "remove" || !change.role.split(",").includes("owner"));
  if (losesOwner) {
    const owners = (await authPool.query<{ n: string }>(`select count(*) as n from member where "organizationId" = $1 and role like '%owner%'`, [orgId])).rows[0]!;
    if (Number(owners.n) <= 1) throw new Error("A business needs at least one owner: make someone else owner first");
  }
  if (change === "remove") await authPool.query(`delete from member where id = $1`, [memberId]);
  else await authPool.query(`update member set role = $1 where id = $2`, [change.role, memberId]);
  return { email: target.email };
}

export async function cancelInvitation(orgId: string, invitationId: string): Promise<{ email: string }> {
  const r = await authPool.query<{ email: string }>(`update invitation set status = 'canceled' where id = $1 and "organizationId" = $2
    and status = 'pending' returning email`, [invitationId, orgId]);
  if (!r.rows[0]) throw new Error("Invitation not found");
  return r.rows[0];
}

/** Does this user already sign in with a password (or only with emailed links)? */
export async function hasPassword(userId: string): Promise<boolean> {
  const r = await authPool.query(`select 1 from account where "userId" = $1 and "providerId" = 'credential' and password is not null limit 1`, [userId]);
  return (r.rowCount ?? 0) > 0;
}

/**
 * Demo logins + client organisations for local development (idempotent).
 * Users go through Better Auth (password hashing); organisations and memberships are inserted directly,
 * because Better Auth's organisation endpoints need a signed-in session.
 * Afterwards run `uv run agentry seed` in backend/ to load the app data for these organisations.
 */
import { randomUUID } from "node:crypto";
import { auth, authPool } from "../src/lib/auth";

const PASSWORD = "agentry-demo-123";

type Seed = { email: string; name: string; platformRole?: "admin"; orgs?: [slug: string, role: string][] };

const orgs = [
  { slug: "sharma-digital", name: "Sharma Digital Agency" },
  { slug: "kaveri-industrial", name: "Kaveri Industrial Supplies" },
  { slug: "brightpath", name: "Brightpath Consulting" },
  { slug: "smilecraft", name: "SmileCraft Dental Clinic" },
  { slug: "agentry", name: "Agentry" }, // our own business: the website chat on the landing page
];

const users: Seed[] = [
  { email: "admin@agentry.dev", name: "Agentry Admin", platformRole: "admin", orgs: [["agentry", "owner"]] },
  { email: "riya@sharmadigital.example", name: "Riya Sharma", orgs: [["sharma-digital", "owner"]] },
  { email: "accounts@sharmadigital.example", name: "Arjun (Accounts)", orgs: [["sharma-digital", "finance"]] },
  { email: "natarajan@kaverisupplies.example", name: "S. Natarajan", orgs: [["kaveri-industrial", "owner"]] },
  { email: "jordan@brightpath.example", name: "Jordan Ellis", orgs: [["brightpath", "owner"]] },
  { email: "neha@smilecraft.example", name: "Dr. Neha Kulkarni", orgs: [["smilecraft", "owner"]] },
  { email: "frontdesk@smilecraft.example", name: "Pooja (Front desk)", orgs: [["smilecraft", "staff"]] },
  // An owner of two businesses, to exercise the org switcher.
  { email: "multi@agentry.dev", name: "Kabir Malhotra", orgs: [["sharma-digital", "viewer"], ["smilecraft", "manager"]] },
];

async function userId(email: string, name: string): Promise<string> {
  const existing = await authPool.query<{ id: string }>(`select id from "user" where email = $1`, [email]);
  if (existing.rows[0]) return existing.rows[0].id;
  const res = await auth.api.signUpEmail({ body: { email, password: PASSWORD, name } });
  await authPool.query(`update "user" set "emailVerified" = true where id = $1`, [res.user.id]);
  return res.user.id;
}

async function orgId(slug: string, name: string): Promise<string> {
  const existing = await authPool.query<{ id: string }>(`select id from organization where slug = $1`, [slug]);
  if (existing.rows[0]) return existing.rows[0].id;
  const id = randomUUID();
  await authPool.query(`insert into organization (id, name, slug, "createdAt") values ($1, $2, $3, now())`, [id, name, slug]);
  return id;
}

const orgIds = new Map<string, string>();
for (const o of orgs) orgIds.set(o.slug, await orgId(o.slug, o.name));

for (const u of users) {
  const id = await userId(u.email, u.name);
  if (u.platformRole) await authPool.query(`update "user" set role = $1 where id = $2`, [u.platformRole, id]);
  for (const [slug, role] of u.orgs ?? []) {
    const oid = orgIds.get(slug)!;
    await authPool.query(
      `insert into member (id, "organizationId", "userId", role, "createdAt")
       select $1, $2, $3, $4, now() where not exists (select 1 from member where "organizationId" = $2 and "userId" = $3)`,
      [randomUUID(), oid, id, role],
    );
  }
  console.log(`${u.email.padEnd(36)} ${u.platformRole ?? (u.orgs ?? []).map(([s, r]) => `${s}:${r}`).join(", ")}`);
}

console.log(`\nAll demo users share the password: ${PASSWORD}`);
await authPool.end();

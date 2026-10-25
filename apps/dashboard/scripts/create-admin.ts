/**
 * Production: create (or promote) an Agentry staff admin and the "Agentry" organisation. Idempotent.
 *   ADMIN_EMAIL=you@agentry.example ADMIN_NAME="Your Name" pnpm exec tsx scripts/create-admin.ts
 * A random password is printed once; afterwards sign in with it or with an emailed magic link.
 */
import { randomBytes, randomUUID } from "node:crypto";
import { auth, authPool } from "../src/lib/auth";

const email = process.env.ADMIN_EMAIL?.trim().toLowerCase();
const name = process.env.ADMIN_NAME?.trim() || "Agentry Admin";
if (!email) throw new Error("set ADMIN_EMAIL");

let userId = (await authPool.query<{ id: string }>(`select id from "user" where email = $1`, [email])).rows[0]?.id;
let password: string | null = null;
if (!userId) {
  password = randomBytes(15).toString("base64url");
  userId = (await auth.api.signUpEmail({ body: { email, password, name } })).user.id;
}
await authPool.query(`update "user" set role = 'admin', "emailVerified" = true where id = $1`, [userId]);

let orgId = (await authPool.query<{ id: string }>(`select id from organization where slug = 'agentry'`)).rows[0]?.id;
if (!orgId) {
  orgId = randomUUID();
  await authPool.query(`insert into organization (id, name, slug, "createdAt") values ($1, 'Agentry', 'agentry', now())`, [orgId]);
}
await authPool.query(
  `insert into member (id, "organizationId", "userId", role, "createdAt")
   select $1, $2, $3, 'owner', now() where not exists (select 1 from member where "organizationId" = $2 and "userId" = $3)`,
  [randomUUID(), orgId, userId],
);
console.log(`${email} is an Agentry admin.`);
if (password) console.log(`Temporary password (shown once): ${password}`);
await authPool.end();

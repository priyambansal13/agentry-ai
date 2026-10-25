/** Create or update Better Auth's tables in schema "auth" (role agentry_auth's search_path). */
import { getMigrations } from "better-auth/db/migration";
import { auth, authPool } from "../src/lib/auth";

const { toBeCreated, toBeAdded, runMigrations } = await getMigrations(auth.options);
console.log(`tables to create: ${toBeCreated.map((t) => t.table).join(", ") || "none"}`);
console.log(`columns to add:   ${toBeAdded.map((t) => t.table).join(", ") || "none"}`);
await runMigrations();
await authPool.end();
console.log("auth schema up to date");

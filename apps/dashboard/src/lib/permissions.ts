import { createAccessControl } from "better-auth/plugins/access";
import rolesConfig from "../../../../config/roles.json";

/** Client roles come from config/roles.json, shared with the Python API. */
type Statements = Record<string, readonly string[]>;
type Permissions = Record<string, string[]>;

const statements = rolesConfig.statements as unknown as Statements;
export const ac = createAccessControl(statements);

export const roleKeys = ["owner", "manager", "staff", "finance", "viewer"] as const;
export type RoleKey = (typeof roleKeys)[number];

export const roles = Object.fromEntries(
  roleKeys.map((key) => [key, ac.newRole(rolesConfig.roles[key].permissions as Permissions)]),
) as Record<RoleKey, ReturnType<typeof ac.newRole>>;

export const roleLabels: Record<RoleKey, string> = Object.fromEntries(
  roleKeys.map((key) => [key, rolesConfig.roles[key].label]),
) as Record<RoleKey, string>;

export function can(role: string | undefined, resource: string, action: string): boolean {
  if (!role) return false;
  return role.split(",").some((r) => {
    const perms = (rolesConfig.roles as Record<string, { permissions: Record<string, string[]> }>)[r.trim()]?.permissions;
    return perms?.[resource]?.includes(action) ?? false;
  });
}

/** Invoice follow-up is money: its conversations and Needs-you cards follow the invoice permission (mirrors
 *  agentry/api/routes/work.py). Everything else follows the conversation permission. */
export function canOnItem(role: string | undefined, automationKey: string | null | undefined, action: "read" | "act"): boolean {
  return can(role, MONEY_AGENTS.includes(automationKey ?? "") ? "invoice" : "conversation", action);
}

/** Agents whose cards and conversations follow the money (invoice) permission, as in the API (approvals.MONEY_AGENTS). */
export const MONEY_AGENTS = ["invoice_follow_up", "bookkeeping"];

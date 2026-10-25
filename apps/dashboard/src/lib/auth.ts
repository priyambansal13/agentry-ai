import { AsyncLocalStorage } from "node:async_hooks";
import { betterAuth } from "better-auth";
import { nextCookies } from "better-auth/next-js";
import { admin, jwt, magicLink, organization } from "better-auth/plugins";
import { Pool } from "pg";
import { sendMail } from "./mail";
import { ac, roles } from "./permissions";

const baseURL = process.env.BETTER_AUTH_URL ?? "http://localhost:3201";

export const authPool = new Pool({ connectionString: process.env.AUTH_DATABASE_URL });

/** While set, a magic link is handed back to the caller instead of emailed: the invitation link (/invite/[id]) turns
 * itself into a one-time sign-in on the spot, so an invited person needs one click, not a second email. */
export const magicLinkCapture = new AsyncLocalStorage<{ url?: string }>();

export const auth = betterAuth({
  appName: "Agentry",
  baseURL,
  secret: process.env.BETTER_AUTH_SECRET,
  database: authPool,
  emailAndPassword: {
    enabled: true,
    minPasswordLength: 10,
    // Forgot password: a one-hour link. It also works for people who have only used emailed sign-in links (it creates
    // their password). Setting a new password signs out every other device.
    resetPasswordTokenExpiresIn: 60 * 60,
    revokeSessionsOnPasswordReset: true,
    sendResetPassword: async ({ user, url }) => {
      await sendMail(
        user.email,
        "Reset your Agentry password",
        `Hi ${user.name?.split(" ")[0] || "there"},\n\nChoose a new password for Agentry: ${url}\n\nThe link expires in 1 hour and works once. `
          + "If you didn't ask for this, ignore this email: your password stays the same.",
      );
    },
  },
  session: { expiresIn: 60 * 60 * 24 * 14, updateAge: 60 * 60 * 24 },
  rateLimit: { enabled: true, window: 60, max: 60 },
  plugins: [
    magicLink({
      expiresIn: 60 * 15,
      sendMagicLink: async ({ email, url }) => {
        const capture = magicLinkCapture.getStore();
        if (capture) {
          capture.url = url;
          return;
        }
        await sendMail(
          email,
          "Your Agentry sign-in link",
          `Sign in to Agentry: ${url}\n\nThe link expires in 15 minutes. If you didn't ask for it, ignore this email.`,
        );
      },
    }),
    organization({
      ac,
      roles,
      creatorRole: "owner",
      // Agency model: Agentry staff create client organisations (from Agentry HQ or a converted demo).
      allowUserToCreateOrganization: async (user) => (user as { role?: string }).role === "admin",
      invitationExpiresIn: 60 * 60 * 24 * 7,
      sendInvitationEmail: async ({ id, email, role, organization: org, inviter }) => {
        const url = `${baseURL}/invite/${id}`;
        await sendMail(
          email,
          `${inviter.user.name} invited you to ${org.name} on Agentry`,
          `${inviter.user.name} invited you to join ${org.name} on Agentry as ${role}.\n\nAccept: ${url}\n\nThis invitation expires in 7 days.`,
        );
      },
    }),
    // Agentry staff are platform admins (user.role = "admin").
    admin({ defaultRole: "user", adminRoles: ["admin"] }),
    // Short-lived JWTs for the Python API, verified there against /api/auth/jwks.
    jwt({
      jwt: {
        issuer: baseURL,
        audience: baseURL,
        expirationTime: "15m",
        definePayload: ({ user, session }) => ({
          email: user.email,
          name: user.name,
          platform_role: (user as { role?: string }).role ?? "user",
          active_org: (session as { activeOrganizationId?: string | null }).activeOrganizationId ?? null,
        }),
      },
    }),
    nextCookies(),
  ],
});

export type Session = typeof auth.$Infer.Session;

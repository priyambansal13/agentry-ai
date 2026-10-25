import nodemailer from "nodemailer";

// Development: every email lands in Mailpit (http://localhost:58025). Production: a real SMTP service with a login.
const transport = nodemailer.createTransport({
  host: process.env.SMTP_HOST ?? "localhost",
  port: Number(process.env.SMTP_PORT ?? 51025),
  secure: process.env.SMTP_SECURE === "true", // true for port 465; port 587 upgrades with STARTTLS automatically
  auth: process.env.SMTP_USER ? { user: process.env.SMTP_USER, pass: process.env.SMTP_PASSWORD ?? "" } : undefined,
});

// RFC 2606/6761 names that can never receive mail (demo clients, test data). With a real mail server configured,
// sending to them would only bounce back to Agentry's inbox; the local Mailpit still receives everything.
const RESERVED = [".example", ".test", ".invalid", ".localhost", "@example.com", "@example.org", "@example.net"];
const LOCAL = ["localhost", "127.0.0.1", "mailpit"].includes(process.env.SMTP_HOST ?? "localhost");

export async function sendMail(to: string, subject: string, text: string, html?: string) {
  if (!LOCAL && RESERVED.some((r) => to.trim().toLowerCase().endsWith(r))) {
    console.info(`not emailing ${to} (reserved demo/test domain): ${subject}`);
    return;
  }
  await transport.sendMail({ from: process.env.MAIL_FROM ?? "Agentry <hello@agentry.dev>", to, subject, text, html });
}

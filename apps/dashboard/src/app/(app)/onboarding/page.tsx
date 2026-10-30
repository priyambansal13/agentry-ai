import { Card, cn } from "@agentry/ui";
import Link from "next/link";
import { redirect } from "next/navigation";
import { AddFaqForm, AddTextForm, LearnWebsiteForm, UploadFileForm } from "@/components/knowledge-forms";
import { GoLive, MarkDone, PersonaStep, ProfileStep, TestChat } from "@/components/onboarding-steps";
import { can } from "@/lib/permissions";
import { api, getActiveOrg, getMe } from "@/lib/session";

export const metadata = { title: "Get live" };

type Profile = {
  name: string; website: string | null; timezone: string; currency: string; phone: string | null; address: string | null;
  city: string | null; customer_value: number | null; persona: { name?: string; tone?: string; greeting?: string; signoff?: string };
  status: string; widget_key: string | null; steps: { key: string; status: string }[];
  automations: string[]; connections: string[]; go_live_checks: { key: string; label: string; done: boolean }[];
};

const STEPS: Record<string, { title: string; hint: string }> = {
  profile: { title: "Business profile", hint: "The basics your agents need" },
  plan: { title: "Plan & agreement", hint: "What you've signed up for" },
  team: { title: "Team", hint: "Who else should sign in" },
  connect: { title: "Connect accounts", hint: "Inbox, website, calendar" },
  import: { title: "Import data", hint: "Old leads, contacts, invoices" },
  knowledge: { title: "Knowledge & offers", hint: "What your agents may say" },
  settings: { title: "Automation settings", hint: "Hours, alerts, tone" },
  persona: { title: "Persona", hint: "Name, tone, first message" },
  compliance: { title: "Compliance", hint: "AI disclosure, quiet hours, consent" },
  test: { title: "Test your agent", hint: "Chat with it like a customer" },
  go_live: { title: "Go live", hint: "Start in approval mode" },
};

export default async function OnboardingPage({ searchParams }: { searchParams: Promise<{ step?: string }> }) {
  const [{ step: requested }, me, active] = await Promise.all([searchParams, getMe(), getActiveOrg()]);
  if (!active) redirect("/home");
  if (!(me.is_staff || can(active.role, "automation", "configure"))) redirect("/home");
  const p = await api<Profile>("/org/profile", { orgId: active.id });
  const done = (k: string) => ["done", "skipped"].includes(p.steps.find((s) => s.key === k)?.status ?? "");
  const step = requested && p.steps.some((s) => s.key === requested) ? requested : p.steps.find((s) => !["done", "skipped"].includes(s.status))?.key ?? "go_live";
  const missing = p.go_live_checks.filter((c) => !c.done).map((c) => c.label);
  const has = (k: string) => p.automations.includes(k);
  const dashboard = process.env.NEXT_PUBLIC_DASHBOARD_URL ?? "http://localhost:3201";
  const api_ = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8801";
  const doneCount = p.steps.filter((s) => done(s.key)).length;

  return (
    <div className="space-y-6">
      <header>
        <p className="font-hand text-xl text-muted">{doneCount} of {p.steps.length} done</p>
        <h1 className="font-display text-3xl font-bold tracking-tight">Let&apos;s get {active.name} <span className="highlight">live</span></h1>
        <p className="mt-1 text-muted">Prefer us to do a step? Tell your Agentry account manager: every step can be done for you.</p>
      </header>
      <div className="grid gap-6 lg:grid-cols-[260px_1fr]">
        <ol className="space-y-1">
          {p.steps.map((s, i) => (
            <li key={s.key}>
              <Link href={`/onboarding?step=${s.key}`} aria-current={s.key === step ? "step" : undefined}
                className={cn("flex items-center gap-3 rounded-xl px-3 py-2 text-sm", s.key === step ? "bg-lime font-semibold text-lime-ink" : "hover:bg-lime-soft")}>
                <span className={cn("grid h-6 w-6 shrink-0 place-items-center rounded-full border-2 text-xs",
                  done(s.key) ? "border-success bg-success text-white" : s.status === "blocked" ? "border-warning text-warning" : "border-line")}>
                  {done(s.key) ? "✓" : s.status === "blocked" ? "!" : i + 1}
                </span>
                {STEPS[s.key]!.title}
              </Link>
            </li>
          ))}
        </ol>
        <Card className="min-w-0 p-6 sm:p-8">
          <h2 className="font-display text-2xl font-bold">{STEPS[step]!.title}</h2>
          <p className="mb-6 text-muted">{STEPS[step]!.hint}</p>
          {step === "profile" && <ProfileStep initial={{ website: p.website, phone: p.phone, address: p.address, city: p.city, timezone: p.timezone, currency: p.currency, customer_value: p.customer_value }} />}
          {step === "plan" && (<div className="space-y-4"><p className="text-ink-soft">Your plan and agreement were set up by Agentry. You can review them any time in Billing.</p><MarkDone step="plan" label="Looks right" /></div>)}
          {step === "team" && (<div className="space-y-4"><p className="text-ink-soft">Invite the people who should see results or approve messages. Front desk staff get a limited role.</p>
            <div className="flex gap-3"><Link href="/team" className="font-semibold underline">Open Team →</Link></div><MarkDone step="team" allowSkip /></div>)}
          {step === "connect" && (
            <div className="space-y-5">
              {has("website_chat") && <div><h3 className="font-semibold">Website chat</h3>
                <p className="text-sm text-muted">Paste this just before &lt;/body&gt; on your website (or email it to your web developer):</p>
                <pre className="mt-2 rounded-xl bg-ink p-4 text-xs break-all whitespace-pre-wrap text-paper">{`<script src="${dashboard}/widget.js" data-key="${p.widget_key}" data-api="${api_}" async></script>`}</pre></div>}
              {has("speed_to_lead") && <div><h3 className="font-semibold">Lead forms</h3>
                <p className="text-sm text-muted">Create a link for each website form or ad source, then send form entries to it. New leads get a message within about a minute.</p>
                <Link href="/leads" className="mt-1 inline-block font-semibold underline">Open Leads → Lead forms</Link></div>}
              {p.connections.includes("gmail") && <div><h3 className="font-semibold">Gmail</h3>
                <p className="text-sm text-muted">{has("inbox_triage") ? "Your agent sorts new mail, labels it and drafts replies in your own Gmail. It never sends without you." : "Reminders go out from your own Gmail address."}</p></div>}
              {p.connections.includes("whatsapp") && <div><h3 className="font-semibold">WhatsApp Business</h3>
                <p className="text-sm text-muted">Messages go out from your own WhatsApp Business number.</p></div>}
              {p.connections.includes("telegram") && <div><h3 className="font-semibold">Telegram bot</h3>
                <p className="text-sm text-muted">Create a bot with @BotFather (two minutes) and paste its token: your assistant answers customers who message it.</p></div>}
              {p.connections.includes("gateways") && <div><h3 className="font-semibold">Razorpay or Stripe</h3>
                <p className="text-sm text-muted">Payments are matched to invoices automatically, so reminders stop the moment a customer pays.</p></div>}
              {p.connections.length > 0 && <Link href="/settings/connections" className="inline-block font-semibold underline">Open Connections →</Link>}
              <p className="text-sm text-muted">Want alerts and approvals on your phone? Connect your own Telegram under <Link href="/settings/account" className="underline">Account &amp; notifications</Link>.</p>
              <MarkDone step="connect" />
            </div>)}
          {step === "import" && (<div className="space-y-4"><p className="text-ink-soft">Send your old leads, contacts or invoices (CSV, Excel or Google Sheet) to your account manager and we&apos;ll import and clean them.</p><MarkDone step="import" allowSkip /></div>)}
          {step === "knowledge" && (<div className="space-y-8"><LearnWebsiteForm defaultUrl={p.website} /><UploadFileForm /><AddTextForm /><AddFaqForm /><Link href="/knowledge" className="text-sm underline">See everything your agents know →</Link></div>)}
          {step === "settings" && (<div className="space-y-4"><p className="text-ink-soft">Review alert hours, quiet hours and what each agent does.</p><Link href="/automations" className="font-semibold underline">Open Automations →</Link><MarkDone step="settings" /></div>)}
          {step === "persona" && <PersonaStep initial={p.persona} />}
          {step === "compliance" && (
            <div className="space-y-4 text-ink-soft">
              <ul className="list-disc space-y-2 pl-5">
                <li>Your agents always say they are an AI assistant.</li>
                <li>No alerts or outbound messages during your quiet hours.</li>
                <li>Anyone who says stop or unsubscribe is never contacted again.</li>
                <li>Imported contact lists must have consent for the channel we use (WhatsApp, SMS, calls).</li>
              </ul>
              <MarkDone step="compliance" label="I understand" />
            </div>)}
          {step === "test" && (<div className="space-y-3"><p className="text-ink-soft">Ask the questions your customers ask. Test chats never count in your results.
            {" "}<Link href="/talk" className="font-semibold underline">Or talk to it by voice →</Link></p><TestChat greeting={p.persona.greeting ?? "Hi! How can I help?"} /></div>)}
          {step === "go_live" && (
            <div className="space-y-4">
              <ul className="space-y-1.5 text-sm">{p.go_live_checks.map((c) => (
                <li key={c.key} className="flex items-center gap-2"><span aria-hidden="true" className={c.done ? "text-success" : "text-muted"}>{c.done ? "✓" : "○"}</span>
                  <span className={c.done ? "" : "text-ink-soft"}>{c.label}</span></li>
              ))}</ul>
              <GoLive ready={missing.length === 0} missing={missing} />
            </div>)}
        </Card>
      </div>
    </div>
  );
}

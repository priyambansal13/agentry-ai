import { Badge, Card, CardBody, CardHeader, CardTitle } from "@agentry/ui";
import Link from "next/link";
import { notFound, redirect } from "next/navigation";
import { type SendingMailbox, SendingMailboxes } from "@/components/cold-email";
import { AutomationSwitches, InviteMember, OpenPortal, PhoneAssign, type PhoneNumber } from "@/components/hq-client";
import { GenerateStatement, type PlanIn, PlanEditor } from "@/components/hq-billing";
import type { CatalogItem } from "@/components/new-client-form";
import { pendingInvitations } from "@/lib/clients";
import { money, STATUS_TONE } from "@/lib/billing";
import { statusLabels } from "@/lib/format";
import { api, ApiError, getMe } from "@/lib/session";

export const metadata = { title: "Client · Agentry HQ" };

type Margin = { month: string; llm_usd: number; transcription_usd?: number; whatsapp_templates: number; voice_minutes: number; cost_inr: number; revenue: Record<string, number>; revenue_inr: number; margin_pct: number | null };
type Detail = {
  org: { name: string; slug: string; status: string | null; industry_pack: string | null; country: string | null; currency: string | null; website: string | null };
  plan: PlanIn | null; margin: Margin; outcomes: Record<string, number>;
  statements: { id: string; number: string; period_start: string; status: string; total: number; currency: string; open_disputes: number }[];
  automations: { template_key: string; status: string }[]; members: { name: string; email: string; role: string }[];
};

function lastMonth() {
  const d = new Date(); d.setUTCDate(1); d.setUTCMonth(d.getUTCMonth() - 1);
  return d.toISOString().slice(0, 7);
}

export default async function HqClient({ params, searchParams }: { params: Promise<{ orgId: string }>; searchParams: Promise<{ created?: string; invite?: string }> }) {
  const [{ orgId }, sp, me] = await Promise.all([params, searchParams, getMe()]);
  if (!me.is_staff) redirect("/home");
  let d: Detail;
  try {
    d = await api<Detail>(`/hq/orgs/${orgId}`);
  } catch (e) {
    if (e instanceof ApiError && e.status === 404) notFound();
    throw e;
  }
  const [{ automations: catalog }, invites] = await Promise.all([api<{ automations: CatalogItem[] }>("/hq/catalog"), pendingInvitations(orgId)]);
  const receptionist = d.automations.some((a) => a.template_key === "ai_receptionist");
  const coldEmail = d.automations.some((a) => a.template_key === "cold_email");
  const mailboxes = coldEmail ? await api<{ items: SendingMailbox[] }>(`/hq/orgs/${orgId}/sending-mailboxes`).then((r) => r.items) : [];
  const phones = receptionist ? await api<{ items: PhoneNumber[] }>("/hq/phone-numbers").then((r) => r.items).catch(() => null) : null;
  const m = d.margin;
  const mLabel = new Date(`${m.month}-01T00:00:00`).toLocaleDateString("en-IN", { month: "long" });
  const disputes = d.statements.reduce((n, s) => n + Number(s.open_disputes), 0);
  const outcome = (k: string) => d.outcomes[k] ?? 0;
  return (
    <div className="space-y-6">
      <Link href="/hq" className="text-sm text-muted hover:text-ink">← All clients</Link>
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="font-display text-3xl font-bold tracking-tight">{d.org.name}</h1>
          <p className="mt-1 text-sm text-muted">{[d.org.industry_pack, d.org.country, d.org.website].filter(Boolean).join(" · ")}</p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Badge tone={statusLabels[d.org.status ?? ""]?.tone ?? "neutral"}>{statusLabels[d.org.status ?? ""]?.label ?? "Not set up"}</Badge>
          {d.org.status && ["onboarding", "pending_setup"].includes(d.org.status) && <OpenPortal orgId={orgId} to="/onboarding" label="Do their onboarding" primary />}
          {d.org.status && <OpenPortal orgId={orgId} />}
        </div>
      </header>
      {sp.created && (
        <p role="status" className="rounded-2xl border-2 border-ink bg-lime px-4 py-3 text-lime-ink">
          ✓ Client created{sp.invite === "invited" ? " and the owner was emailed an invitation" : sp.invite === "added" ? "; the owner already had a login and was added" : ""}.
          Next: do their onboarding (or let the owner do it), then go live.
        </p>
      )}

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <Card className="p-5"><p className="text-sm text-muted">Revenue, {mLabel}</p><p className="mt-1 text-2xl font-semibold">{money(m.revenue_inr, "INR")}</p>
          <p className="text-xs text-muted">{Object.entries(m.revenue).map(([c, v]) => money(v, c)).join(" + ") || "no statements"}</p></Card>
        <Card className="p-5"><p className="text-sm text-muted">Cost to serve, {mLabel}</p><p className="mt-1 text-2xl font-semibold">{money(m.cost_inr, "INR")}</p>
          <p className="text-xs text-muted">${m.llm_usd.toFixed(2)} models{m.transcription_usd ? ` · $${m.transcription_usd.toFixed(2)} transcription` : ""} · {m.whatsapp_templates} WhatsApp templates · {m.voice_minutes} call min</p></Card>
        <Card className="p-5"><p className="text-sm text-muted">Gross margin</p><p className="mt-1 text-2xl font-semibold">{m.margin_pct != null ? `${m.margin_pct}%` : "—"}</p>
          <p className="text-xs text-muted">rough: FX and template costs are estimates</p></Card>
        <Card className="p-5"><p className="text-sm text-muted">Billable results (all time)</p>
          <p className="mt-1 text-2xl font-semibold">{outcome("appointment_booked:billable") + outcome("amount_recovered:billable")}</p>
          <p className="text-xs text-muted">{outcome("appointment_booked:billable")} bookings · {outcome("amount_recovered:billable")} recoveries · {outcome("amount_recovered:excluded") + outcome("appointment_booked:excluded")} excluded</p></Card>
      </div>

      <Card>
        <CardHeader><CardTitle>Statements</CardTitle>{disputes > 0 && <Badge tone="warning">{disputes} open dispute{disputes === 1 ? "" : "s"}</Badge>}</CardHeader>
        <CardBody className="space-y-4">
          <GenerateStatement orgId={orgId} defaultMonth={lastMonth()} />
          <table className="w-full text-left text-sm">
            <tbody className="divide-y divide-line">
              {d.statements.length === 0 && <tr><td className="py-4 text-muted">No statements yet.</td></tr>}
              {d.statements.map((s) => (
                <tr key={s.id}>
                  <td className="py-2.5 font-mono text-xs">{s.number}</td>
                  <td className="py-2.5">{new Date(s.period_start).toLocaleDateString("en-IN", { month: "long", year: "numeric" })}</td>
                  <td className="py-2.5"><Badge tone={STATUS_TONE[s.status] ?? "neutral"}>{s.status}</Badge>
                    {Number(s.open_disputes) > 0 && <Badge tone="warning" className="ml-2">{s.open_disputes} disputed</Badge>}</td>
                  <td className="py-2.5 text-right tabular-nums">{money(s.total, s.currency)}</td>
                  <td className="py-2.5 text-right"><Link className="font-semibold underline-offset-4 hover:underline" href={`/hq/${orgId}/statements/${s.id}`}>Open →</Link></td>
                </tr>
              ))}
            </tbody>
          </table>
        </CardBody>
      </Card>

      <Card>
        <CardHeader><CardTitle>Pricing plan</CardTitle><span className="text-sm text-muted">{d.plan ? "changes apply to the next statement" : "no plan yet"}</span></CardHeader>
        <CardBody><PlanEditor orgId={orgId} plan={d.plan} automations={d.automations.map((a) => a.template_key)} /></CardBody>
      </Card>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card><CardHeader><CardTitle>Automations</CardTitle><span className="text-sm text-muted">what the client sees follows these</span></CardHeader><CardBody>
          <AutomationSwitches orgId={orgId} catalog={catalog} current={d.automations} />
          {receptionist && (
            <div className="mt-4 border-t border-line pt-4">
              <p className="mb-2 font-semibold">Phone number</p>
              {phones ? <PhoneAssign orgId={orgId} numbers={phones} /> : <p className="text-sm text-danger">Couldn&apos;t reach LiveKit to list numbers.</p>}
            </div>
          )}
          {coldEmail && (
            <div className="mt-4 border-t border-line pt-4">
              <p className="mb-2 font-semibold">Cold email sending mailboxes</p>
              <SendingMailboxes orgId={orgId} items={mailboxes} />
            </div>
          )}
        </CardBody></Card>
        <Card><CardHeader><CardTitle>Team</CardTitle></CardHeader><CardBody className="space-y-4">
          <ul className="divide-y divide-line text-sm">{d.members.map((u) => (
            <li key={u.email} className="flex justify-between gap-3 py-2"><span>{u.name} <span className="text-muted">{u.email}</span></span><span className="text-muted">{u.role}</span></li>
          ))}{invites.map((i) => (
            <li key={i.email} className="flex justify-between gap-3 py-2"><span className="text-muted">{i.email}</span><span className="text-muted">{i.role} · invited</span></li>
          ))}{d.members.length + invites.length === 0 && <li className="py-2 text-muted">Nobody yet: invite the owner.</li>}</ul>
          <InviteMember orgId={orgId} orgName={d.org.name} />
        </CardBody></Card>
      </div>
    </div>
  );
}

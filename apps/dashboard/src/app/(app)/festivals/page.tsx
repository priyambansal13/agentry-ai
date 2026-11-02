import { Badge, Card, CardBody, CardHeader, CardTitle } from "@agentry/ui";
import { CopyText } from "@/components/ca-tool-forms";
import { PlanButton, PlanStatus } from "@/components/festivals";
import { day } from "@/lib/ca";
import { api, requirePage } from "@/lib/session";

export const metadata = { title: "Festival campaigns" };

type Plan = { id: string; festival: string; name: string; on_date: string; status: string; checks: string[];
  plan: { theme?: string; posts?: { platform: string; text: string }[]; whatsapp?: string; greeting?: string; timeline?: { when: string; what: string }[] } };
type D = { upcoming: { key: string; name: string; date: string; lunar: boolean }[]; chosen: string[]; plans: Plan[]; can_edit: boolean };

export default async function FestivalsPage() {
  const active = await requirePage("festivals");
  const d = await api<D>("/org/festivals", { orgId: active.id });
  const planned = new Set(d.plans.map((p) => `${p.festival}:${p.on_date}`));
  return (
    <div className="space-y-6">
      <header>
        <h1 className="font-display text-3xl font-bold tracking-tight">Festival campaigns</h1>
        <p className="mt-1 max-w-3xl text-muted">Weeks before each festival you picked, a plan: posts, a WhatsApp message for your customers, a greeting for the day and when to send
          what. Offers are only ever the ones you set in settings.</p>
      </header>
      <Card><CardHeader><CardTitle>Coming up (next 4 months)</CardTitle></CardHeader><CardBody>
        <ul className="divide-y divide-line">{d.upcoming.map((f) => (
          <li key={`${f.key}${f.date}`} className="flex flex-wrap items-center justify-between gap-2 py-2 text-sm">
            <span><span className="font-medium">{f.name}</span> · {day(f.date)}{f.lunar && <span className="text-xs text-muted"> (lunar date: check it)</span>}
              {!d.chosen.includes(f.key) && <span className="text-xs text-muted"> · not in your list</span>}</span>
            {d.can_edit && !planned.has(`${f.key}:${f.date}`) ? <PlanButton festival={f.key} date={f.date} /> : <Badge>planned</Badge>}
          </li>))}</ul></CardBody></Card>
      {d.plans.map((p) => (
        <Card key={p.id}><CardHeader><CardTitle>{p.name} · {day(p.on_date)}</CardTitle>
          <span className="flex items-center gap-2"><Badge tone={p.status === "needs_attention" ? "warning" : p.status === "approved" ? "success" : "neutral"}>{p.status.replace("_", " ")}</Badge>
            {d.can_edit && <PlanStatus id={p.id} status={p.status} />}</span></CardHeader>
          <CardBody className="space-y-3 text-sm">
            {p.checks.length > 0 && <p className="text-warning">Check: {p.checks.join("; ")}</p>}
            {p.plan.theme && <p className="font-medium">{p.plan.theme}</p>}
            {(p.plan.posts ?? []).map((x, i) => <div key={i} className="rounded-xl bg-paper p-3"><p className="flex justify-between text-xs text-muted">{x.platform}<CopyText text={x.text} /></p>
              <p className="whitespace-pre-wrap">{x.text}</p></div>)}
            {p.plan.whatsapp && <div className="rounded-xl bg-lime-soft p-3"><p className="flex justify-between text-xs text-muted">WhatsApp to customers<CopyText text={p.plan.whatsapp} /></p><p>{p.plan.whatsapp}</p></div>}
            {p.plan.greeting && <p><span className="text-muted">On the day:</span> {p.plan.greeting}</p>}
            {(p.plan.timeline ?? []).length > 0 && <ul className="list-disc pl-5">{p.plan.timeline!.map((t) => <li key={t.when}><span className="font-medium">{t.when}:</span> {t.what}</li>)}</ul>}
          </CardBody></Card>))}
    </div>
  );
}

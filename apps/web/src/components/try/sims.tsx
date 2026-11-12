"use client";

import { CheckCircle2, Clock, Plus } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { type Any, Bubble, Field, fmtDate, inr, Panel, RunButton, Select, Stat, TryShell, useRun } from "./kit";

/* ---------- speed-to-lead: a lead form, answered in a minute ---------- */

const SLOTS = ["Tomorrow 11:00", "Tomorrow 17:30", "Saturday 10:00"];

export function SpeedToLeadBox() {
  const [f, setF] = useState({ name: "Priya", need: "Teeth whitening", business: "SmileCraft Dental" });
  const [step, setStep] = useState<"form" | "waiting" | "sent" | "booked">("form");
  const [secs, setSecs] = useState(0);
  const [slot, setSlot] = useState<string | null>(null);
  const timer = useRef<ReturnType<typeof setInterval> | null>(null);
  const [leads, setLeads] = useState(120);
  const [late, setLate] = useState(40);
  const [value, setValue] = useState(8000);
  useEffect(() => () => { if (timer.current) clearInterval(timer.current); }, []);
  function submit() {
    setStep("waiting"); setSecs(0); setSlot(null);
    timer.current = setInterval(() => setSecs((s) => {
      if (s >= 57) { clearInterval(timer.current!); setStep("sent"); return 58; }
      return s + 3;
    }), 80);
  }
  const first = f.name.split(" ")[0] || "there";
  return (
    <TryShell title="Every new lead gets a reply in about a minute"
      intro="Fill in the form as if you were a customer on the business's website or a Facebook ad. Watch what lands on your WhatsApp, then reply and book (the clock is sped up)."
      sell="In the portal this works for website forms, Google and Meta lead ads and IndiaMART. The assistant takes over the chat, answers from your knowledge and books into your calendar. Opt-outs are honoured.">
      <div className="grid gap-6 lg:grid-cols-[1fr_22rem]">
        <div className="space-y-4">
          <div className="grid gap-3 sm:grid-cols-3">
            <Field id="sl-n" label="Your name" value={f.name} onChange={(v) => setF({ ...f, name: v })} />
            <Field id="sl-need" label="Looking for" value={f.need} onChange={(v) => setF({ ...f, need: v })} />
            <Field id="sl-b" label="Business" value={f.business} onChange={(v) => setF({ ...f, business: v })} />
          </div>
          <button type="button" onClick={submit} disabled={step === "waiting"} className="inline-flex h-12 items-center rounded-xl bg-ink px-6 font-semibold text-paper hover:opacity-90 disabled:opacity-50">Submit the enquiry</button>
          <div className="grid gap-3 rounded-2xl border-2 border-ink bg-card p-4 sm:grid-cols-3">
            <Field id="sl-l" label="Leads a month" type="number" value={leads} onChange={(v) => setLeads(Number(v) || 0)} />
            <Field id="sl-late" label="% answered after an hour" type="number" value={late} onChange={(v) => setLate(Number(v) || 0)} />
            <Field id="sl-v" label="Value of a customer (₹)" type="number" value={value} onChange={(v) => setValue(Number(v) || 0)} />
            <p className="text-sm sm:col-span-3">If even 1 in 10 of the late ones goes to whoever replied first, that&apos;s <strong>{Math.round((leads * late) / 1000)} customers</strong> and <strong>{inr(Math.round((leads * late) / 1000) * value)}</strong> a month walking away.</p>
          </div>
        </div>
        <div className="rounded-[2rem] border-2 border-ink bg-card p-3 shadow-[6px_6px_0_0_var(--ink)]">
          <p className="rounded-t-[1.5rem] bg-ink px-4 py-3 font-semibold text-paper">{f.business}</p>
          <div className="min-h-[22rem] space-y-3 bg-paper p-3">
            {step === "form" && <p className="pt-24 text-center text-sm text-muted">Your WhatsApp. Submit the form to see what arrives.</p>}
            {step === "waiting" && <p className="flex items-center justify-center gap-2 pt-24 text-sm"><Clock aria-hidden="true" className="h-4 w-4 animate-pulse" /> enquiry received · {secs}s</p>}
            {(step === "sent" || step === "booked") && <>
              <Bubble from="them" meta={`58 seconds after the form`}>{`Hi ${first}, thanks for your enquiry about ${f.need.toLowerCase()} at ${f.business}! I can help you book a visit. Would any of these suit you?\n${SLOTS.map((s) => `• ${s}`).join("\n")}\n\nOr ask me anything about it.`}</Bubble>
              {step === "sent" && <div className="flex flex-wrap justify-end gap-2">{SLOTS.map((s) => <button key={s} type="button" onClick={() => { setSlot(s); setStep("booked"); }} className="rounded-full border-2 border-ink bg-card px-3 py-1 text-xs font-semibold hover:bg-lime">{s}</button>)}</div>}
              {step === "booked" && <><Bubble>{slot} please</Bubble><Bubble from="them" meta="booked in the calendar">{`Done! You're booked for ${slot} at ${f.business}. You'll get a reminder the day before. Reply here if anything changes.`}</Bubble></>}
            </>}
          </div>
        </div>
      </div>
    </TryShell>
  );
}

/* ---------- ops dispatcher: jobs to the right technician ---------- */

type Tech = { name: string; skills: string[]; areas: string[]; max: number };
type Job = { n: number; customer: string; service: string; area: string; slot: string };
const TECHS: Tech[] = [
  { name: "Imran", skills: ["AC service", "AC repair"], areas: ["Kothrud", "Baner"], max: 3 },
  { name: "Suresh", skills: ["Plumbing"], areas: ["Kothrud", "Hadapsar", "Baner"], max: 4 },
  { name: "Vikas", skills: ["AC service", "Electrical"], areas: ["Hadapsar", "Kharadi"], max: 3 },
];
const JOBS: Job[] = [
  { n: 1041, customer: "Anita Desai", service: "AC service", area: "Kothrud", slot: "morning" },
  { n: 1042, customer: "Rahul Shah", service: "AC repair", area: "Baner", slot: "afternoon" },
  { n: 1043, customer: "Meera Joshi", service: "Plumbing", area: "Hadapsar", slot: "morning" },
  { n: 1044, customer: "Farhan Ali", service: "Electrical", area: "Kharadi", slot: "evening" },
  { n: 1045, customer: "Sneha Patil", service: "AC service", area: "Kharadi", slot: "afternoon" },
];
const match = (a: string, b: string) => !!a && !!b && (a.toLowerCase().includes(b.toLowerCase()) || b.toLowerCase().includes(a.toLowerCase()));

export function DispatcherBox() {
  const [jobs, setJobs] = useState(JOBS);
  const [plan, setPlan] = useState<{ job: Job; tech: Tech | null; why: string }[] | null>(null);
  const [nj, setNj] = useState({ customer: "Kavita Rao", service: "AC repair", area: "Kothrud", slot: "evening" });
  function assign() {
    const load: Record<string, number> = {};
    setPlan(jobs.map((job) => {
      const fit = TECHS.filter((t) => t.skills.some((s) => match(s, job.service)) && t.areas.some((a) => match(a, job.area)) && (load[t.name] ?? 0) < t.max);
      const t = fit.sort((a, b) => (load[a.name] ?? 0) - (load[b.name] ?? 0) || a.name.localeCompare(b.name))[0] ?? null;
      if (t) load[t.name] = (load[t.name] ?? 0) + 1;
      const why = t ? `does ${job.service}, covers ${job.area}, ${load[t.name]} of ${t.max} jobs today` : `nobody does ${job.service} in ${job.area} with room today: the office picks someone`;
      return { job, tech: t, why };
    }));
  }
  const day = new Date(Date.now() + 86400000).toLocaleDateString("en-IN", { weekday: "short", day: "numeric", month: "short" });
  const first = plan?.find((p) => p.tech);
  return (
    <TryShell title="Every service call, on one board"
      intro="Tomorrow's jobs came in from WhatsApp and calls. Add one of your own, then assign them all: each goes to a technician who has the skill, covers the area and has room in the day. See what the technician and the customer get."
      sell="In the portal your WhatsApp assistant books the visits, the office sees one board, customers get “on the way” and “done”, and finished jobs become invoices that chase themselves. No app for technicians to install.">
      <div className="grid gap-4 lg:grid-cols-[1.4fr_1fr]">
        <Panel title="Tomorrow's jobs"><ul className="space-y-1 text-sm">{jobs.map((j) => <li key={j.n} className="flex justify-between gap-2 border-b border-line py-1 last:border-0"><span>#{j.n} {j.customer}</span><span className="text-ink-soft">{j.service} · {j.area} · {j.slot}</span></li>)}</ul>
          <div className="mt-3 grid gap-2 border-t border-line pt-3 sm:grid-cols-[1fr_1fr_1fr_auto] sm:items-end">
            <Field id="dp-c" label="Customer" value={nj.customer} onChange={(v) => setNj({ ...nj, customer: v })} />
            <Select id="dp-s" label="Service" value={nj.service} onChange={(v) => setNj({ ...nj, service: v })} options={["AC service", "AC repair", "Plumbing", "Electrical"].map((s) => [s, s])} />
            <Select id="dp-a" label="Area" value={nj.area} onChange={(v) => setNj({ ...nj, area: v })} options={["Kothrud", "Baner", "Hadapsar", "Kharadi", "Wakad"].map((s) => [s, s])} />
            <button type="button" onClick={() => { setJobs([...jobs, { n: 1040 + jobs.length + 1, ...nj }]); setPlan(null); }} className="inline-flex h-11 items-center gap-1 rounded-xl border-2 border-ink bg-card px-3 text-sm font-semibold hover:bg-lime"><Plus aria-hidden="true" className="h-4 w-4" /> Add</button>
          </div></Panel>
        <Panel title="Technicians"><ul className="space-y-2 text-sm">{TECHS.map((t) => <li key={t.name}><strong>{t.name}</strong>: {t.skills.join(", ")}<br /><span className="text-ink-soft">{t.areas.join(", ")} · up to {t.max} a day</span></li>)}</ul></Panel>
      </div>
      <button type="button" onClick={assign} className="mt-4 inline-flex h-12 items-center rounded-xl bg-ink px-6 font-semibold text-paper hover:opacity-90">Assign the jobs</button>
      {plan && (
        <div className="mt-6 grid gap-4 lg:grid-cols-[1.4fr_1fr]">
          <Panel title="The board"><ul className="space-y-2 text-sm">{plan.map(({ job, tech, why }) => (
            <li key={job.n} className="flex flex-wrap items-start justify-between gap-2 border-b border-line pb-2 last:border-0"><span>#{job.n} {job.customer} · {job.service}</span>
              <span className={tech ? "text-right" : "text-right text-danger"}><strong>{tech?.name ?? "Unassigned"}</strong><br /><span className="text-xs text-ink-soft">{why}</span></span></li>))}</ul></Panel>
          {first && <Panel title="On WhatsApp">
            <div className="space-y-3">
              <p className="text-xs font-semibold text-muted">To {first.tech!.name}</p>
              <Bubble>{`Job #${first.job.n}: ${first.job.service}\n${day} (${first.job.slot})\n${first.job.customer}\n${first.job.area}`}</Bubble>
              <p className="text-xs font-semibold text-muted">To {first.job.customer}</p>
              <Bubble>{`Hi ${first.job.customer.split(" ")[0]}, ${first.tech!.name} is on the way for your ${first.job.service}. Reply here if you need anything.`}</Bubble>
              <Bubble meta="when the office marks it done">{`Your ${first.job.service} is done. Here's your invoice: pay by UPI or card at the link. Thank you!`}</Bubble>
            </div></Panel>}
        </div>)}
    </TryShell>
  );
}

/* ---------- renewals (the real reminder schedule from the backend) ---------- */

export function RenewalsBox() {
  const [f, setF] = useState({ business: "CoolAir Services", customer: "Anita Desai", item: "AC annual maintenance", amount: 4500, due_on: new Date(Date.now() + 40 * 86400000).toISOString().slice(0, 10), every: "yearly", offer: "10% off if you renew this week" });
  const r = useRun("renewals", false);
  const x: Any = r.result;
  return (
    <TryShell title="Money you're already owed, collected on time"
      intro="An AMC, membership, policy or subscription that's coming due. See the reminders the customer gets 30, 7 and 1 days before (with a payment link when there's an amount), the win-back if it lapses, and when the next one is due."
      sell="In the portal renewals come from your sheet, each reminder carries a Razorpay link, it stops the moment they pay, and birthday wishes go out once a year.">
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Field id="rn-b" label="Your business" value={f.business} onChange={(v) => setF({ ...f, business: v })} />
        <Field id="rn-c" label="Customer" value={f.customer} onChange={(v) => setF({ ...f, customer: v })} />
        <Field id="rn-i" label="What renews" value={f.item} onChange={(v) => setF({ ...f, item: v })} />
        <Field id="rn-a" label="Amount (₹)" type="number" value={f.amount} onChange={(v) => setF({ ...f, amount: Number(v) || 0 })} />
        <Field id="rn-d" label="Due on" type="date" value={f.due_on} onChange={(v) => setF({ ...f, due_on: v })} />
        <Select id="rn-e" label="Renews every" value={f.every} onChange={(v) => setF({ ...f, every: v })} options={[["monthly", "Month"], ["quarterly", "Quarter"], ["half_yearly", "6 months"], ["yearly", "Year"]]} />
        <div className="sm:col-span-2"><Field id="rn-o" label="Win-back offer (optional)" value={f.offer} onChange={(v) => setF({ ...f, offer: v })} /></div>
      </div>
      <div className="mt-4"><RunButton r={r} label="Show the reminders" input={() => f} /></div>
      {x && (
        <div className="mt-6 grid gap-4 lg:grid-cols-[1.5fr_1fr]">
          <Panel title="Before it's due"><div className="space-y-3">{x.reminders.map((m: Any) => <Bubble key={m.label} meta={`${m.label} · ${fmtDate(m.when)}`}>{m.text}</Bubble>)}</div></Panel>
          <div className="space-y-4">
            <Panel title="If it lapses"><Bubble meta={`15 days after · ${fmtDate(x.winback.when)}`}>{x.winback.text}</Bubble></Panel>
            <Stat label="When they pay" value={<span className="inline-flex items-center gap-2"><CheckCircle2 aria-hidden="true" className="h-6 w-6 text-success" /> next due {fmtDate(x.next_due)}</span>} note="Reminders stop; the next cycle is set up." />
          </div>
        </div>)}
    </TryShell>
  );
}

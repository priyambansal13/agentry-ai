"use client";

import { AlertTriangle, Camera, CheckCircle2, ExternalLink, Quote, ShieldAlert, XCircle } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { type Any, Area, Bubble, Copyable, Field, fileToDataUrl, fmtDate, inr, Markdown, Panel, Presets, RunButton, Select, Severity, Stat, TryShell, useRun, useSample } from "./kit";

/* ---------- lead research ---------- */

export function LeadResearchBox() {
  const [site, setSite] = useState("");
  const [msg, setMsg] = useState("Hi, do you do this for businesses like ours? What would it cost?");
  const [offer, setOffer] = useState("");
  const r = useRun("lead-research", true);
  const x = r.result;
  return (
    <TryShell live title="Know who you're talking to before you call"
      intro="Pretend a lead just filled your form. Type their company's website and what they wrote. In under a minute you get the note your team would see: what they do, how big they are, what they probably need and what to ask. Every point comes from their own pages."
      sell="In the portal every new lead is researched within a minute, and the night before a meeting you get a one-page brief on WhatsApp.">
      <div className="grid gap-3 md:grid-cols-2">
        <Field id="lr-site" label="The lead's company website" value={site} onChange={setSite} placeholder="clovedental.in" />
        <Field id="lr-offer" label="What you sell (optional)" value={offer} onChange={setOffer} placeholder="WhatsApp marketing for clinics" />
      </div>
      <div className="mt-3"><Area id="lr-msg" label="What they wrote" value={msg} onChange={setMsg} rows={2} /></div>
      <div className="mt-4"><RunButton r={r} label="Research this lead" input={() => ({ website: site, message: msg, offer })} disabled={site.length < 4} /></div>
      {x && (
        <div className="mt-6 grid gap-4 lg:grid-cols-[1.4fr_1fr]">
          <Panel title={x.company ?? x.domain}>
            <dl className="space-y-3 text-sm">
              {x.what_they_do && <div><dt className="font-semibold">What they do</dt><dd className="text-ink-soft">{x.what_they_do}</dd></div>}
              {x.size && <div><dt className="font-semibold">Size</dt><dd className="text-ink-soft">{x.size}</dd></div>}
              {x.decision_maker && <div><dt className="font-semibold">Decision maker named on their site</dt><dd className="text-ink-soft">{x.decision_maker.name}, {x.decision_maker.role}</dd></div>}
              {x.likely_need && <div><dt className="font-semibold">Probably wants</dt><dd className="text-ink-soft">{x.likely_need}</dd></div>}
            </dl>
          </Panel>
          <div className="space-y-4">
            {x.talking_points?.length > 0 && <Panel title="Worth raising"><ul className="ml-5 list-disc space-y-1 text-sm">{x.talking_points.map((t: string) => <li key={t}>{t}</li>)}</ul></Panel>}
            {x.questions?.length > 0 && <Panel title="Ask them"><ul className="ml-5 list-disc space-y-1 text-sm">{x.questions.map((t: string) => <li key={t}>{t}</li>)}</ul></Panel>}
            <p className="text-xs text-muted">Read from: {x.sources?.slice(0, 4).map((u: string) => u.replace(/^https?:\/\//, "")).join(", ")}. Numbers not on those pages are dropped.</p>
          </div>
        </div>)}
    </TryShell>
  );
}

/* ---------- personal cold email ---------- */

export function ColdEmailBox() {
  const [site, setSite] = useState("");
  const [offer, setOffer] = useState("WhatsApp reminders that cut no-shows");
  const [first, setFirst] = useState("");
  const r = useRun("cold-email", true);
  const x = r.result;
  return (
    <TryShell live title="A first line that proves you looked"
      intro="Type a prospect's website and what you sell. The writer reads their pages, picks a real fact, writes one personal opening line from it, and a fact-checker rejects anything the website doesn't say. You see the fact it used."
      sell="In the portal prospects come from Google Maps lists, each gets a checked first line, you approve the batch, and it sends slowly from warmed-up inboxes. Replies are sorted for you.">
      <div className="grid gap-3 md:grid-cols-3">
        <Field id="ce-site" label="Prospect's website" value={site} onChange={setSite} placeholder="kapoorsmilestudio.in" />
        <Field id="ce-first" label="Their first name (optional)" value={first} onChange={setFirst} />
        <Field id="ce-offer" label="What you sell" value={offer} onChange={setOffer} />
      </div>
      <div className="mt-4"><RunButton r={r} label="Write the email" input={() => ({ website: site, offer, first_name: first })} disabled={site.length < 4} /></div>
      {x && (
        <div className="mt-6 grid gap-4 lg:grid-cols-[1.3fr_1fr]">
          <Panel title="The email (you'd review it first)" action={x.email ? <Copyable text={x.email} /> : undefined}>
            {x.email ? <p className="text-sm whitespace-pre-line">{x.email}</p>
              : <p className="text-sm text-danger">{x.line?.reason ?? "Nothing on their website to base a line on."}</p>}
          </Panel>
          <Panel title="Fact check">
            {x.line?.line && <p className={`flex gap-2 text-sm font-semibold ${x.line.ok ? "text-success" : "text-danger"}`}>{x.line.ok ? <CheckCircle2 aria-hidden="true" className="h-5 w-5" /> : <XCircle aria-hidden="true" className="h-5 w-5" />}
              {x.line.ok ? `Passed${x.line.attempts > 1 ? ` (first try was rejected and rewritten)` : ""}` : `Rejected: ${x.line.reason}`}</p>}
            {x.facts?.filter((f: Any) => f.n === x.line?.snippet).map((f: Any) => (
              <blockquote key={f.n} className="mt-3 border-l-4 border-ink pl-3 text-sm text-ink-soft"><Quote aria-hidden="true" className="mb-1 h-4 w-4" />{f.text}
                <a href={f.url} target="_blank" rel="noreferrer" className="mt-1 flex items-center gap-1 text-xs underline">{f.url.replace(/^https?:\/\//, "")} <ExternalLink aria-hidden="true" className="h-3 w-3" /></a></blockquote>))}
          </Panel>
        </div>)}
    </TryShell>
  );
}

/* ---------- inbox triage ---------- */

const EMAILS = [
  { label: "Bank details changed", value: { from: "accounts@kaveritextile.in", from_name: "Kaveri Textiles Accounts", subject: "Invoice 2231 - updated bank details",
    body: "Dear Sir,\n\nPlease note our bank account has changed. Kindly transfer the pending ₹1,84,000 for invoice 2231 to the new account below by today.\n\nHDFC A/c 50200011223344, IFSC HDFC0001234\n\nRegards,\nAccounts" } },
  { label: "New enquiry", value: { from: "neha@urbanbites.in", from_name: "Neha Kapoor", subject: "Instagram ads for our 3 cafes",
    body: "Hi, we run 3 cafes in Pune and want someone to handle Instagram and Zomato ads from December. Budget is around 40k a month. Can we talk this week?" } },
  { label: "Angry client (Hinglish)", value: { from: "rohan@northstarrealty.in", from_name: "Rohan Mehta", subject: "Ads band ho gaye??",
    body: "Riya, kal raat se hamare Meta ads 'rejected' dikha rahe hain. Launch event kal hai. Please ASAP fix karo, bahut urgent hai." } },
];

export function InboxBox() {
  const [e, setE] = useState(EMAILS[0]!.value);
  const [facts, setFacts] = useState("");
  const r = useRun("inbox", true);
  const x = r.result;
  return (
    <TryShell live title="Your inbox, sorted, with fraud caught"
      intro="Pick a sample email or paste one. You'll see the label, whether it's urgent and why, any fraud warning (changed bank details, lookalike domains, OTP requests), and a reply drafted in the same language."
      sell="In the portal every Gmail or Outlook email is labelled within a minute, urgent ones ping the right person on WhatsApp, and replies are drafted from your real prices for you to send.">
      <Presets items={EMAILS} onPick={(v) => setE(v)} />
      <div className="mt-3 grid gap-3 md:grid-cols-2">
        <Field id="ib-from" label="From" value={e.from} onChange={(v) => setE({ ...e, from: v })} />
        <Field id="ib-sub" label="Subject" value={e.subject} onChange={(v) => setE({ ...e, subject: v })} />
      </div>
      <div className="mt-3 grid gap-3 md:grid-cols-[1.5fr_1fr]">
        <Area id="ib-body" label="Email" value={e.body} onChange={(v) => setE({ ...e, body: v })} rows={6} />
        <Area id="ib-facts" label="Facts the reply may use (optional)" value={facts} onChange={setFacts} rows={6} placeholder="e.g. Social media management starts at ₹25,000/month. Free call slots Tue and Thu." />
      </div>
      <div className="mt-4"><RunButton r={r} label="Triage this email" input={() => ({ ...e, facts })} /></div>
      {x && (
        <div className="mt-6 space-y-4">
          <div className="grid gap-3 sm:grid-cols-3">
            <Stat label="Label" value={x.category} note={x.summary} />
            <Stat label="Urgent" value={x.urgent ? "Yes" : "No"} note={x.urgent_reason ?? undefined} />
            <Stat label="Needs a reply" value={x.needs_reply ? "Yes" : "No"} note={x.entities?.amount ? `Amount: ${inr(x.entities.amount)}` : undefined} />
          </div>
          {x.risk?.length > 0 && <Panel tone="warn" title={<span className="inline-flex items-center gap-2 text-danger"><ShieldAlert aria-hidden="true" className="h-5 w-5" /> Possible fraud: don&apos;t pay before calling them</span>}>
            <ul className="ml-5 list-disc space-y-1 text-sm">{x.risk.map((w: string) => <li key={w}>{w}</li>)}</ul></Panel>}
          {x.reply && <Panel title="Draft reply (waits for your OK)" action={<Copyable text={x.reply} />}><p className="text-sm whitespace-pre-line">{x.reply}</p></Panel>}
        </div>)}
    </TryShell>
  );
}

/* ---------- SOP & proposal drafter ---------- */

function Mermaid({ code }: { code: string }) {
  const ref = useRef<HTMLDivElement>(null);
  const [failed, setFailed] = useState(false);
  const [drawn, setDrawn] = useState(false);
  useEffect(() => {
    let off = false;
    (async () => {
      try {
        const load = new Function("u", "return import(u)") as (u: string) => Promise<Any>;
        const m = (await load("https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.esm.min.mjs")).default;
        m.initialize({ startOnLoad: false, theme: "neutral", securityLevel: "strict" });
        const { svg } = await m.render(`sop${Date.now()}`, code);
        if (!off && ref.current) { ref.current.innerHTML = svg; setDrawn(true); }
      } catch { if (!off) setFailed(true); }
    })();
    return () => { off = true; };
  }, [code]);
  if (failed) return <pre className="overflow-auto rounded-xl bg-paper p-3 text-xs">{code}</pre>;
  return <>{!drawn && <p className="text-sm text-muted">Drawing the flowchart…</p>}<div ref={ref} className="flex justify-center overflow-x-auto [&_svg]:max-w-full" aria-label="Flowchart" role="img" /></>;
}

const BRIEFS = {
  sop: "How the front desk opens the clinic every morning: lights and AC, sterilizer on, check today's appointments, call to confirm, update the waitlist.",
  proposal: "Proposal for Urban Bites (3 cafes in Pune): Instagram and Zomato ads, 12 posts a month, monthly report. Our fee is ₹40,000 a month, 3-month minimum.",
  checklist: "Onboarding checklist for a new receptionist at a dental clinic: first day, first week, who trains them on what.",
};

export function DocBox() {
  const [kind, setKind] = useState<"sop" | "proposal" | "checklist">("sop");
  const [brief, setBrief] = useState(BRIEFS.sop);
  const [biz, setBiz] = useState("SmileCraft Dental");
  const r = useRun("doc", true);
  const x = r.result;
  return (
    <TryShell live title="Write it down once, run it forever"
      intro="Pick SOP, proposal or checklist and describe it in a sentence or two. You get a finished document, and an SOP comes with a flowchart. Any price or number that isn't in your brief is caught and sent back for a rewrite."
      sell="In the portal it also uses your services and prices, you edit and finalise it in the browser, and download it as Word or PDF for the team.">
      <div className="grid gap-3 md:grid-cols-[12rem_14rem_1fr]">
        <Select id="dc-kind" label="Document" value={kind} onChange={(v) => { setKind(v as typeof kind); setBrief(BRIEFS[v as keyof typeof BRIEFS]); }} options={[["sop", "SOP"], ["proposal", "Proposal"], ["checklist", "Checklist"]]} />
        <Field id="dc-biz" label="Business" value={biz} onChange={setBiz} />
        <Area id="dc-brief" label="Describe it" value={brief} onChange={setBrief} rows={3} />
      </div>
      <div className="mt-4"><RunButton r={r} label="Draft it" input={() => ({ kind, brief, business: biz })} /></div>
      {x && (
        <div className={`mt-6 grid gap-4 ${x.diagram ? "lg:grid-cols-[1.2fr_1fr]" : ""}`}>
          <Panel title={x.title}><div className="max-h-[32rem] overflow-auto"><Markdown text={x.content} /></div>
            {x.problems?.length > 0 && <p className="mt-3 text-sm text-danger">Needs a look: {x.problems.join("; ")}</p>}</Panel>
          {x.diagram && <Panel title="Flowchart"><Mermaid code={x.diagram} /></Panel>}
        </div>)}
    </TryShell>
  );
}

/* ---------- festival campaigns ---------- */

export function FestivalBox() {
  const s = useSample("festival");
  const [f, setF] = useState({ festival: "", business: "SmileCraft Dental", about: "family dental clinic in Pune", offer: "Free check-up for kids this week", language: "English" });
  useEffect(() => { if (s?.festivals?.[0]) setF((v) => ({ ...v, festival: s.festivals[0].key })); }, [s]);
  const r = useRun("festival", true);
  const x = r.result;
  return (
    <TryShell live title="Your next festival campaign, ready weeks ahead"
      intro="Pick the festival and tell it about the business and any offer. You get a theme, posts, a WhatsApp message to customers, a greeting for the day and a timeline. Any discount or number that isn't your offer gets flagged and rewritten."
      sell="In the portal every festival on your calendar gets its plan weeks before, you approve it on your phone, and it's scheduled. Nothing is broadcast by itself.">
      <div className="grid gap-3 md:grid-cols-5">
        <Select id="fs-f" label="Festival" value={f.festival} onChange={(v) => setF({ ...f, festival: v })} options={(s?.festivals ?? []).map((x: Any) => [x.key, `${x.name} · ${fmtDate(x.date)}`])} />
        <Field id="fs-b" label="Business" value={f.business} onChange={(v) => setF({ ...f, business: v })} />
        <Field id="fs-a" label="What you do" value={f.about} onChange={(v) => setF({ ...f, about: v })} />
        <Field id="fs-o" label="Your offer (optional)" value={f.offer} onChange={(v) => setF({ ...f, offer: v })} />
        <Select id="fs-l" label="Language" value={f.language} onChange={(v) => setF({ ...f, language: v })} options={[["English", "English"], ["Hinglish", "Hinglish"], ["Hindi", "Hindi"], ["Marathi", "Marathi"]]} />
      </div>
      <div className="mt-4"><RunButton r={r} label="Plan the campaign" input={() => f} disabled={!s} /></div>
      {x && (
        <div className="mt-6 space-y-4">
          <div className="rounded-2xl border-2 border-ink bg-lime p-5 text-lime-ink"><p className="text-sm font-semibold">{x.festival.name} · {fmtDate(x.festival.date)}</p><p className="font-display text-2xl font-bold">{x.plan.theme}</p></div>
          <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
            {x.plan.posts?.map((p: Any, i: number) => <Panel key={i} title={p.platform}><p className="text-sm whitespace-pre-line">{p.text}</p></Panel>)}
            <Panel title="WhatsApp to customers"><Bubble>{x.plan.whatsapp}</Bubble></Panel>
            <Panel title="On the day"><p className="text-sm">{x.plan.greeting}</p>
              {x.plan.timeline?.length > 0 && <ol className="mt-3 space-y-1 border-t border-line pt-3 text-xs">{x.plan.timeline.map((t: Any) => <li key={t.when}><strong>{t.when}:</strong> {t.what}</li>)}</ol>}</Panel>
          </div>
          {x.problems?.length > 0 && <p className="text-sm text-danger">Flagged for you: {x.problems.join("; ")}</p>}
        </div>)}
    </TryShell>
  );
}

/* ---------- content repurposing ---------- */

export function ContentBox() {
  const s = useSample("content");
  const [t, setT] = useState("");
  const [sp, setSp] = useState("");
  useEffect(() => { if (s) { setT(s.text); setSp(s.speaker); } }, [s]);
  const r = useRun("content", true);
  const x = r.result;
  return (
    <TryShell live title="One recording, a week of posts"
      intro="A sample podcast transcript is filled in, or paste your own talk, video transcript or article. You get a LinkedIn post, an Instagram caption and an X post. Each post is built on a sentence the speaker really said, and that quote is checked word for word."
      sell="In the portal one weekly recording becomes about 30 posts, branded quote cards and captioned vertical clips. You approve them, they post on schedule, and it learns what works.">
      <div className="grid gap-3 md:grid-cols-[16rem_1fr]">
        <Field id="ct-sp" label="Speaker" value={sp} onChange={setSp} />
        <Area id="ct-t" label="Transcript or article" value={t} onChange={setT} rows={7} />
      </div>
      <div className="mt-4"><RunButton r={r} label="Make the posts" input={() => ({ text: t, speaker: sp })} /></div>
      {x && <div className="mt-6 grid gap-4 lg:grid-cols-3">{x.posts.map((p: Any, i: number) => (
        <Panel key={i} title={p.platform === "x" ? "X" : p.platform === "linkedin" ? "LinkedIn" : "Instagram"}>
          <p className="text-sm whitespace-pre-line">{p.text}</p>
          <div className="mt-3 border-t border-line pt-3 text-xs"><p className={`flex items-center gap-1 font-semibold ${p.quote_checked ? "text-success" : "text-danger"}`}>
            {p.quote_checked ? <CheckCircle2 aria-hidden="true" className="h-4 w-4" /> : <AlertTriangle aria-hidden="true" className="h-4 w-4" />}{p.quote_checked ? "Quote found word for word" : "Quote not found: would be held back"}</p>
            <p className="mt-1 text-ink-soft">“{p.quote}”</p></div>
          <div className="mt-2 flex justify-end"><Copyable text={p.text} /></div>
        </Panel>))}</div>}
    </TryShell>
  );
}

/* ---------- AI video studio ---------- */

export function VideoBox() {
  const [f, setF] = useState({ business: "SmileCraft Dental", about: "family dental clinic in Pune", topic: "Why your gums bleed when you brush", cta: "Book a check-up on WhatsApp", language: "English" });
  const r = useRun("video", true);
  const x = r.result;
  return (
    <TryShell live title="A Short, scripted in seconds"
      intro="Give a topic. You get the shot-by-shot script for a 30-60 second Short: the hook, what's said, what's on screen, the caption and the hashtags. It's checked for guarantees, prices and superlatives before any money is spent making the video."
      sell="In the portal topics come from your services each week, Google Veo makes the scenes, your captions, logo and end card are added, and you approve from your phone or let it post to YouTube.">
      <div className="grid gap-3 md:grid-cols-5">
        <Field id="vd-b" label="Business" value={f.business} onChange={(v) => setF({ ...f, business: v })} />
        <Field id="vd-a" label="What you do" value={f.about} onChange={(v) => setF({ ...f, about: v })} />
        <Field id="vd-t" label="Topic" value={f.topic} onChange={(v) => setF({ ...f, topic: v })} />
        <Field id="vd-c" label="Ending ask" value={f.cta} onChange={(v) => setF({ ...f, cta: v })} />
        <Select id="vd-l" label="Language" value={f.language} onChange={(v) => setF({ ...f, language: v })} options={[["English", "English"], ["Hinglish", "Hinglish"], ["Hindi", "Hindi"]]} />
      </div>
      <div className="mt-4"><RunButton r={r} label="Write the script" input={() => f} /></div>
      {x && (
        <div className="mt-6 grid gap-4 lg:grid-cols-[1.5fr_1fr]">
          <Panel title={`“${x.script.hook}”`}>
            <ol className="space-y-3">{x.script.beats?.map((b: Any, i: number) => (
              <li key={i} className="grid grid-cols-[4rem_1fr] gap-3 text-sm"><span className="font-mono text-xs text-muted">{b.at}</span>
                <div><p>{b.say}</p><p className="mt-0.5 text-xs text-ink-soft">🎬 {b.show}{b.on_screen ? ` · on screen: “${b.on_screen}”` : ""}</p></div></li>))}</ol>
            <p className="mt-3 border-t border-line pt-3 text-sm font-semibold">{x.script.cta}</p>
          </Panel>
          <div className="space-y-4">
            <Panel title="Caption"><p className="text-sm">{x.script.caption}</p><p className="mt-2 text-sm text-ink-soft">{x.script.hashtags?.join(" ")}</p><p className="mt-2 text-xs text-muted">{x.script.seconds} seconds</p></Panel>
            <Panel tone={x.checks.length ? "warn" : "good"} title="Checks before filming">{x.checks.length ? <ul className="ml-5 list-disc text-sm">{x.checks.map((c: string) => <li key={c}>{c}</li>)}</ul>
              : <p className="flex items-center gap-2 text-sm"><CheckCircle2 aria-hidden="true" className="h-5 w-5 text-success" /> No guarantees, invented prices or superlatives.</p>}</Panel>
          </div>
        </div>)}
    </TryShell>
  );
}

/* ---------- hiring assistant ---------- */

const CVS = [
  { label: "Strong fit", value: "Asha Verma\nasha.verma@example.com | +91 98200 11223\nMarried, female, age: 29\n\nFront desk executive, Sunrise Dental Clinic, Pune (2021 - present)\n- Manage appointments for 3 dentists on Practo and WhatsApp, about 40 patients a day\n- Handle billing and daily cash in Tally; close the day's accounts\n- Call patients the day before to confirm; cut no-shows noticeably\n\nReceptionist, City Hospital (2019 - 2021)\n- Registration and insurance paperwork\n\nLanguages: English, Hindi, Marathi" },
  { label: "Partial fit", value: "Rahul Jadhav\nrahul.j@example.com\n\nSales associate, Croma, Pune (2022 - present)\n- Helped customers choose laptops and phones; top seller in Q3 2024\n- Billing on the store POS\n\nCustomer care intern, Airtel (2021)\n- Answered calls about bills and plans\n\nLanguages: Hindi, Marathi, basic English" },
];

export function HiringBox() {
  const [title, setTitle] = useState("Clinic receptionist");
  const [must, setMust] = useState("Appointment scheduling, Billing in Tally, Marathi");
  const [cv, setCv] = useState(CVS[0]!.value);
  const r = useRun("hiring", true);
  const x = r.result;
  return (
    <TryShell live title="CVs scored with the reasons quoted"
      intro="Set the role and the must-haves, then paste a CV (or use a sample). You get a score out of 100, the strengths with the exact words from the CV, the gaps, and interview questions. Age, gender, marital status and religion are removed before the AI reads the CV."
      sell="In the portal it writes the job post with an apply link, scores every CV as it arrives, books interviews and sends polite regrets. 200 CVs, shortlisted by lunch.">
      <div className="grid gap-3 md:grid-cols-2">
        <Field id="hr-t" label="Role" value={title} onChange={setTitle} />
        <Field id="hr-m" label="Must-haves (comma separated)" value={must} onChange={setMust} />
      </div>
      <div className="mt-3"><Presets items={CVS} onPick={setCv} label="Sample CVs" /></div>
      <div className="mt-3"><Area id="hr-cv" label="CV text (don't paste a real person's CV)" value={cv} onChange={setCv} rows={8} /></div>
      <div className="mt-4"><RunButton r={r} label="Score this CV" input={() => ({ title, must_have: must, cv })} /></div>
      {x && (
        <div className="mt-6 grid gap-4 lg:grid-cols-[14rem_1fr_1fr]">
          <div className={`rounded-2xl border-2 border-ink p-5 ${x.verdict === "strong" ? "bg-lime text-lime-ink" : "bg-card"}`}>
            <p className="text-xs font-semibold uppercase tracking-wide">Score</p><p className="font-display text-5xl font-bold">{x.score}</p>
            <p className="mt-1 font-semibold capitalize">{x.verdict === "no" ? "Not a fit" : x.verdict}</p><p className="mt-2 text-sm">{x.summary}</p>
            {x.hidden?.length > 0 && <p className="mt-3 text-xs">Hidden from the AI: {x.hidden.join(", ")}</p>}
          </div>
          <Panel title="Strengths, quoted from the CV"><ul className="space-y-3 text-sm">{x.strengths?.map((s: Any) => (
            <li key={s.point}><p className="font-semibold">{s.point}</p><p className="text-ink-soft">“{s.quote}”</p></li>))}</ul>
            {x.gaps?.length > 0 && <><p className="mt-4 text-sm font-semibold">Gaps</p><ul className="ml-5 list-disc text-sm text-danger">{x.gaps.map((g: Any) => <li key={g.point}>{g.point}</li>)}</ul></>}</Panel>
          <Panel title="Ask in the interview"><ol className="ml-5 list-decimal space-y-2 text-sm">{x.questions?.map((q: string) => <li key={q}>{q}</li>)}</ol></Panel>
        </div>)}
    </TryShell>
  );
}

/* ---------- bookkeeping: read a bill ---------- */

const FIELD_LABEL: Record<string, string> = { vendor: "Vendor", vendor_gstin: "GSTIN", bill_number: "Bill no.", date: "Date", subtotal: "Before tax", cgst: "CGST", sgst: "SGST", igst: "IGST", total: "Total", category: "Category", payment_method: "Paid by" };
const BILLS = [["supplier-tax-invoice.png", "Supplier tax invoice"], ["grocery-receipt.jpg", "Grocery receipt"], ["cafe-receipt-smudged.jpg", "Smudged café bill"]] as const;

export function BillBox() {
  const [pick, setPick] = useState<string>(BILLS[0][0]);
  const [file, setFile] = useState<{ url: string; name: string } | null>(null);
  const r = useRun("bill", true);
  const x = r.result;
  return (
    <TryShell live title="Snap the bill. It's in the books."
      intro="Pick a sample bill or upload a photo or PDF of your own. The AI reads it, then code checks it: totals add up, CGST equals SGST, the GSTIN's check digit is valid, the date makes sense. Anything doubtful is held back for a person instead of being filed."
      sell="In the portal staff send bills on WhatsApp, Telegram or email. Confident ones are filed and categorised, duplicates are caught, and the month exports to Tally or a sheet.">
      <div className="flex flex-wrap gap-3">
        {BILLS.map(([f, l]) => (
          <button key={f} type="button" onClick={() => { setPick(f); setFile(null); }} aria-pressed={!file && pick === f}
            className={`overflow-hidden rounded-xl border-2 text-left ${!file && pick === f ? "border-ink ring-2 ring-ink" : "border-line"}`}>
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img src={`/samples/${f}`} alt="" className="h-28 w-24 bg-white object-cover object-top" /><span className="block bg-card px-2 py-1 text-xs font-semibold">{l}</span></button>))}
        <label className={`grid w-24 cursor-pointer place-items-center rounded-xl border-2 border-dashed p-2 text-center text-xs font-semibold ${file ? "border-ink bg-lime" : "border-ink/40 bg-card hover:border-ink"}`}>
          <Camera aria-hidden="true" className="h-6 w-6" />{file ? file.name.slice(0, 18) : "Your own bill"}
          <input type="file" accept="image/*,application/pdf" className="sr-only" onChange={async (e) => { const f = e.target.files?.[0]; if (f) setFile({ url: await fileToDataUrl(f), name: f.name }); }} /></label>
      </div>
      <div className="mt-4"><RunButton r={r} label="Read the bill" input={() => (file ? { image: file.url } : { sample: pick })} /></div>
      {x && (x.is_document ? (
        <div className="mt-6 grid gap-4 lg:grid-cols-[1.3fr_1fr]">
          <Panel title="What it read"><dl className="grid grid-cols-[8rem_1fr_auto] gap-x-3 gap-y-1.5 text-sm">{Object.entries(FIELD_LABEL).map(([k, l]) => {
            const f = x.fields[k]; if (!f || f.value === null || f.value === undefined) return null;
            return [<dt key={`${k}l`} className="text-ink-soft">{l}</dt>, <dd key={`${k}v`} className="font-medium">{typeof f.value === "number" ? inr(f.value, 2) : k === "date" ? fmtDate(f.value) : String(f.value)}</dd>,
              <dd key={`${k}c`} className={`text-right text-xs tabular-nums ${f.confidence < 0.85 ? "font-bold text-danger" : "text-muted"}`}>{Math.round(f.confidence * 100)}%</dd>];
          })}</dl></Panel>
          <div className="space-y-4">
            <div className={`rounded-2xl border-2 p-5 ${x.status === "ready" ? "border-ink bg-lime text-lime-ink" : "border-danger bg-card"}`}>
              <p className="font-display text-xl font-bold">{x.status === "ready" ? "Filed automatically" : "Held for a person to check"}</p>
              <p className="mt-1 text-sm">Weakest field: {Math.round(x.confidence * 100)}% sure.</p></div>
            <Panel title="Code checks">{x.checks.length ? <ul className="space-y-2 text-sm">{x.checks.map((c: Any) => <li key={c.code}><Severity level={c.severity} /> {c.message}</li>)}</ul>
              : <p className="flex items-center gap-2 text-sm"><CheckCircle2 aria-hidden="true" className="h-5 w-5 text-success" /> Totals, GST split, GSTIN and date all check out.</p>}</Panel>
          </div>
        </div>) : <p className="mt-6 text-sm text-danger">That doesn&apos;t look like a bill or receipt.</p>)}
    </TryShell>
  );
}

/* ---------- stock shelf scanner ---------- */

export function ShelfBox() {
  const [file, setFile] = useState<{ url: string; name: string } | null>(null);
  const [mins, setMins] = useState<Record<string, number>>({});
  const r = useRun("shelf", true);
  const x = r.result;
  const low = (x?.items ?? []).filter((i: Any) => i.count < (mins[i.name] ?? 6));
  const msg = low.length ? `Hi, please send:\n${low.map((i: Any) => `• ${i.name}: ${Math.max(1, (mins[i.name] ?? 6) * 2 - i.count)} ${i.unit}`).join("\n")}\nThank you!` : "";
  return (
    <TryShell live title="Snap the shelf. Know what to reorder."
      intro="Upload a photo of a shelf, rack or store-room (from your phone is fine). Each item is counted, with how sure it is of the count. Set the minimum you like to keep and the reorder message writes itself."
      sell="In the portal staff send a shelf photo on WhatsApp, counts update your stock list, doubtful counts are highlighted for a person, and reorder lists are grouped by supplier ready to send.">
      <label className={`flex cursor-pointer items-center gap-3 rounded-2xl border-2 border-dashed p-4 ${file ? "border-ink bg-card" : "border-ink/40 bg-card hover:border-ink"}`}>
        {/* eslint-disable-next-line @next/next/no-img-element */}
        {file ? <img src={file.url} alt="Your shelf photo" className="h-24 w-32 rounded-lg object-cover" /> : <Camera aria-hidden="true" className="h-8 w-8" />}
        <span className="text-sm font-semibold">{file ? "Change photo" : "Choose or take a shelf photo"}</span>
        <input type="file" accept="image/*" capture="environment" className="sr-only" onChange={async (e) => { const f = e.target.files?.[0]; if (f) setFile({ url: await fileToDataUrl(f), name: f.name }); }} />
      </label>
      {!file && <button type="button" className="mt-2 text-sm font-semibold underline underline-offset-4" onClick={async () => {
        const blob = await (await fetch("/samples/shelf-sample.jpg")).blob();
        setFile({ url: await fileToDataUrl(new File([blob], "shelf-sample.jpg", { type: "image/jpeg" })), name: "Sample kirana shelf" });
      }}>No photo handy? Use our sample kirana shelf</button>}
      <div className="mt-4"><RunButton r={r} label="Count the stock" input={() => ({ image: file?.url })} disabled={!file} /></div>
      {x && (x.items.length ? (
        <div className="mt-6 grid gap-4 lg:grid-cols-[1.4fr_1fr]">
          <div className="overflow-x-auto rounded-2xl border-2 border-ink bg-card"><table className="w-full text-sm"><thead><tr className="bg-paper text-left text-xs">{["Item", "Counted", "Sure", "Keep at least"].map((h) => <th key={h} className="px-3 py-2">{h}</th>)}</tr></thead>
            <tbody>{x.items.map((i: Any) => (<tr key={i.name} className="border-t border-line"><td className="px-3 py-1.5">{i.name}</td><td className="px-3 py-1.5 font-semibold tabular-nums">{i.count} {i.unit}</td>
              <td className={`px-3 py-1.5 text-xs ${i.confidence < 0.7 ? "font-bold text-danger" : "text-muted"}`}>{Math.round(i.confidence * 100)}%{i.confidence < 0.7 ? " · check" : ""}</td>
              <td className="px-3 py-1"><input type="number" min={0} aria-label={`Minimum for ${i.name}`} value={mins[i.name] ?? 6} onChange={(e) => setMins({ ...mins, [i.name]: Number(e.target.value) || 0 })} className="w-20 rounded-lg border-2 border-line bg-paper px-2 py-1" /></td></tr>))}</tbody></table></div>
          <Panel title="Reorder on WhatsApp">{msg ? <><Bubble>{msg}</Bubble><div className="mt-2 flex justify-end"><Copyable text={msg} /></div></> : <p className="text-sm">Nothing below your minimums.</p>}</Panel>
        </div>) : <p className="mt-6 text-sm text-danger">Couldn&apos;t count anything in that photo: try a clearer, closer shot of the shelf.</p>)}
    </TryShell>
  );
}

/* ---------- lead reactivation ---------- */

export function ReactivationBox() {
  const [f, setF] = useState({ business: "SmileCraft Dental", first_name: "Rahul", interest: "clear aligners", when: "about 8 months ago", offer: "" });
  const [leads, setLeads] = useState(400);
  const [value, setValue] = useState(35000);
  const won = Math.round(leads * 0.03);
  const r = useRun("reactivation", true);
  const x = r.result;
  return (
    <TryShell live title="Money hiding in your old leads"
      intro="Describe one old lead: what they asked about and when. You get the three-message sequence they'd receive: personal, short, no invented offers, and the last one offers to stop. Then see what your own old list could be worth."
      sell="In the portal old leads are imported from your sheet or CRM, messaged one by one at a gentle pace (only those with consent), and keen ones are re-qualified and booked by the assistant.">
      <div className="grid gap-3 md:grid-cols-5">
        <Field id="ra-b" label="Business" value={f.business} onChange={(v) => setF({ ...f, business: v })} />
        <Field id="ra-n" label="Lead's first name" value={f.first_name} onChange={(v) => setF({ ...f, first_name: v })} />
        <Field id="ra-i" label="Asked about" value={f.interest} onChange={(v) => setF({ ...f, interest: v })} />
        <Field id="ra-w" label="When" value={f.when} onChange={(v) => setF({ ...f, when: v })} />
        <Field id="ra-o" label="Offer (optional)" value={f.offer} onChange={(v) => setF({ ...f, offer: v })} />
      </div>
      <div className="mt-4"><RunButton r={r} label="Write the messages" input={() => f} /></div>
      {x && <div className="mt-6 grid gap-4 lg:grid-cols-3">{x.messages.map((m: Any) => (
        <Panel key={m.step} title={m.step === 1 ? "Day 0" : `Day ${m.after_days}`}><p className="text-sm font-semibold">{m.subject}</p><p className="mt-2 text-sm whitespace-pre-line text-ink-soft">{m.body}</p></Panel>))}</div>}
      <div className="mt-6 grid gap-3 rounded-2xl border-2 border-ink bg-card p-4 sm:grid-cols-[1fr_1fr_1.4fr] sm:items-end">
        <Field id="ra-l" label="Old leads on your list" type="number" value={leads} onChange={(v) => setLeads(Number(v) || 0)} />
        <Field id="ra-v" label="Value of one customer (₹)" type="number" value={value} onChange={(v) => setValue(Number(v) || 0)} />
        <p className="text-sm">At a cautious 3% coming back: <strong className="font-display text-xl">{won} customers ≈ {inr(won * value)}</strong></p>
      </div>
    </TryShell>
  );
}

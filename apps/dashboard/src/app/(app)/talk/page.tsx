import { Card, CardBody, CardHeader, CardTitle } from "@agentry/ui";
import { redirect } from "next/navigation";
import { VoiceConsole } from "@/components/voice-console";
import { RetentionForm } from "@/components/voice-settings";
import { can } from "@/lib/permissions";
import { api, getActiveOrg, getFeatures, getMe } from "@/lib/session";

export const metadata = { title: "Talk to your agent" };

const CONVERSATIONAL = ["website_chat", "whatsapp_assistant", "lead_reactivation", "speed_to_lead", "ai_receptionist"];

export default async function TalkPage() {
  const [me, active] = await Promise.all([getMe(), getActiveOrg()]);
  if (!active) redirect("/home");
  if (!(me.is_staff || can(active.role, "automation", "configure"))) redirect("/home");
  const { automations } = await getFeatures(active.id);
  const ok = automations.some((a) => CONVERSATIONAL.includes(a));
  const voice = await api<{ recording_retention_days: number; recording: boolean }>("/org/voice/settings", { orgId: active.id });
  return (
    <div className="space-y-6">
      <header>
        <p className="font-hand text-xl text-muted">New · voice</p>
        <h1 className="font-display text-3xl font-bold tracking-tight">Talk to your agent</h1>
        <p className="mt-1 text-muted">Hear how your agent sounds on a phone call. It answers from your knowledge, can check availability and book.</p>
      </header>
      <Card><CardHeader><CardTitle>Test call</CardTitle></CardHeader><CardBody>
        {ok ? <VoiceConsole /> : <p className="text-sm text-muted">Voice works with a conversational agent (website chat, WhatsApp, receptionist or a lead agent). Ask Agentry to switch one on.</p>}
      </CardBody></Card>
      {ok && (
        <Card><CardHeader><CardTitle>Call recordings</CardTitle></CardHeader><CardBody className="space-y-3">
          <p className="text-sm text-muted">{voice.recording
            ? "Calls are recorded (every call starts with \"This call may be recorded\"). Recordings are deleted automatically after this many days; you can also delete one from its conversation."
            : "Call recording is switched off."}</p>
          {voice.recording && <RetentionForm days={voice.recording_retention_days} />}
        </CardBody></Card>
      )}
    </div>
  );
}

"use client";

import { Badge, Button } from "@agentry/ui";
import { ConnectionState, Room, RoomEvent, Track } from "livekit-client";
import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { startTestCall } from "@/app/(app)/actions";

type Line = { id: string; who: "you" | "agent"; text: string; final: boolean };
const STATE_LABEL: Record<string, string> = { listening: "Listening", thinking: "Thinking…", speaking: "Speaking", initializing: "Joining…" };

/** Talk to your agent in the browser: the same voice pipeline a phone call will use (LiveKit + speech + Agentry's agent). */
export function VoiceConsole() {
  const room = useRef<Room | null>(null);
  const audio = useRef<HTMLDivElement>(null);
  const [status, setStatus] = useState<"idle" | "connecting" | "live" | "ended">("idle");
  const [agentName, setAgentName] = useState("Your agent");
  const [agentState, setAgentState] = useState("initializing");
  const [lines, setLines] = useState<Line[]>([]);
  const [conversation, setConversation] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => () => { void room.current?.disconnect(); }, []);

  async function start() {
    setError(null); setLines([]); setStatus("connecting");
    const r = await startTestCall();
    if (!r.ok) { setError(r.error); setStatus("idle"); return; }
    setAgentName(r.data.agent); setConversation(r.data.conversation_id);
    const rm = new Room({ adaptiveStream: true, dynacast: true });
    room.current = rm;
    rm.registerTextStreamHandler("lk.transcription", async (reader, participant) => {
      const id = reader.info.attributes?.["lk.segment_id"] ?? reader.info.id;
      const who: Line["who"] = participant.identity.startsWith("tester-") ? "you" : "agent";
      const final = reader.info.attributes?.["lk.transcription_final"] === "true";
      let text = "";
      for await (const chunk of reader) {
        text += chunk;
        setLines((ls) => {
          const i = ls.findIndex((l) => l.id === id);
          const line = { id, who, text, final };
          return i === -1 ? [...ls, line] : ls.map((l, j) => (j === i ? line : l));
        });
      }
    });
    rm.on(RoomEvent.TrackSubscribed, (track) => {
      if (track.kind === Track.Kind.Audio) audio.current?.appendChild(track.attach());
    });
    rm.on(RoomEvent.ParticipantAttributesChanged, (changed) => {
      if (changed["lk.agent.state"]) setAgentState(changed["lk.agent.state"]);
    });
    rm.on(RoomEvent.Disconnected, () => setStatus("ended"));
    try {
      await rm.connect(r.data.url, r.data.token);
      await rm.localParticipant.setMicrophoneEnabled(true);
      setStatus("live");
    } catch (e) {
      setError(e instanceof Error && /Permission|NotAllowed/.test(e.message)
        ? "Allow microphone access in your browser to talk to your agent." : `Couldn't start the call: ${(e as Error).message}`);
      await rm.disconnect(); setStatus("idle");
    }
  }

  async function end() {
    await room.current?.disconnect();
    room.current = null;
    setStatus("ended");
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-3">
        {status === "live" || status === "connecting"
          ? <Button variant="secondary" onClick={end} disabled={status === "connecting"}>End call</Button>
          : <Button onClick={start}>{status === "ended" ? "Call again" : `Call ${agentName === "Your agent" ? "your agent" : agentName}`}</Button>}
        {status === "connecting" && <Badge>Connecting…</Badge>}
        {status === "live" && <Badge tone={agentState === "speaking" ? "lime" : agentState === "thinking" ? "warning" : "success"}>
          {agentName}: {STATE_LABEL[agentState] ?? agentState}</Badge>}
        {status === "ended" && conversation && <Link href={`/conversations/${conversation}`} className="text-sm font-semibold underline-offset-4 hover:underline">See the transcript in Conversations →</Link>}
      </div>
      {error && <p role="alert" className="text-sm text-danger">{error}</p>}
      <div ref={audio} className="hidden" aria-hidden="true" />
      <ol className="max-h-96 space-y-2 overflow-y-auto" aria-live="polite">
        {lines.length === 0 && status === "live" && <li className="text-sm text-muted">Say hello. {agentName} greets you first, then listens.</li>}
        {lines.map((l) => (
          <li key={l.id} className={`flex ${l.who === "you" ? "justify-end" : "justify-start"}`}>
            <span className={`max-w-[80%] rounded-2xl px-4 py-2 text-sm ${l.who === "you" ? "bg-ink text-paper" : "border border-line bg-card"} ${l.final ? "" : "opacity-70"}`}>
              {l.text}
            </span>
          </li>
        ))}
      </ol>
      <p className="text-xs text-muted">This is a test call: it uses your microphone, never counts in your results, and the transcript is saved for you to review.
        Phone numbers come next: the same agent will answer your real line.</p>
    </div>
  );
}

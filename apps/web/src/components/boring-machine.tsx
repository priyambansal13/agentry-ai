"use client";

import { cn } from "@agentry/ui";
import { useMemo } from "react";
import { sk, Stroke, useDrawOnView } from "./sketch";

const SOURCES: [string, string][] = [
  ["Cold email", "outbound"],
  ["Website chat", "visitors"],
  ["Speed-to-lead", "new leads"],
  ["Receptionist", "calls"],
  ["Reactivation", "old leads"],
];

/** The reference "#1 The boring machine": five sources → one lead engine → a calendar filling with bookings. */
export function BoringMachine({ className }: { className?: string }) {
  const { ref, drawn } = useDrawOnView<SVGSVGElement>();
  const W = 1000, H = 470;
  const g = useMemo(() => {
    const src = SOURCES.map((_, i) => {
      const y = 18 + i * 88;
      return { y, box: sk.rect(10, y, 230, 70, { seed: 100 + i }), arrow: [
        ...sk.line(250, y + 35, 392, 150 + i * 42, { seed: 200 + i }),
      ] };
    });
    const funnel = sk.polygon([[400, 60], [600, 170], [600, 300], [400, 410]], { seed: 300 });
    const out = [...sk.line(612, 235, 700, 235, { seed: 301 }), ...sk.line(688, 225, 700, 235, { seed: 302 }), ...sk.line(688, 245, 700, 235, { seed: 303 })];
    const cal = sk.rect(712, 92, 276, 250, { seed: 304 });
    const header = [...sk.rect(712, 92, 276, 46, { seed: 305 }), ...sk.line(780, 80, 780, 104, { seed: 306 }), ...sk.line(920, 80, 920, 104, { seed: 307 })];
    const cells = Array.from({ length: 20 }, (_, k) => {
      const c = k % 5, r = Math.floor(k / 5);
      return { x: 724 + c * 52, y: 150 + r * 46, d: sk.rect(724 + c * 52, 150 + r * 46, 44, 36, { seed: 400 + k, roughness: 0.8 }) };
    });
    return { src, funnel, out, cal, header, cells };
  }, []);
  // Order in which slots get booked: scattered, like a real week filling up.
  const bookOrder = [7, 2, 13, 18, 0, 11, 5, 16, 9, 3, 14, 19, 6, 1, 12, 17, 8, 4, 15, 10];

  return (
    <svg ref={ref} viewBox={`0 0 ${W} ${H}`} role="img"
      aria-label="Cold email, website chat, speed-to-lead, receptionist and reactivation all feed one lead engine, which fills a calendar with booked appointments."
      className={cn("sketch w-full text-ink", drawn && "drawn", className)}>
      {g.src.map((s, i) => (
        <g key={i}>
          {s.box.map((d, j) => <Stroke key={j} d={d} i={i} />)}
          {s.arrow.map((d, j) => <Stroke key={`a${j}`} d={d} i={i + 3} />)}
          <text x={125} y={s.y + 34} textAnchor="middle" className="fill-ink font-hand" fontSize="30">{SOURCES[i]![0]}</text>
          <text x={125} y={s.y + 58} textAnchor="middle" className="fill-muted font-hand" fontSize="20">{SOURCES[i]![1]}</text>
        </g>
      ))}
      <path d={g.funnel.join(" ")} fill="var(--card)" stroke="none" />
      {g.funnel.map((d, j) => <Stroke key={j} d={d} i={6} />)}
      <text x={500} y={226} textAnchor="middle" className="fill-ink font-hand" fontSize="32">one lead</text>
      <text x={500} y={262} textAnchor="middle" className="fill-ink font-hand" fontSize="32">engine</text>
      {g.out.map((d, j) => <Stroke key={j} d={d} i={8} />)}
      {g.cal.map((d, j) => <Stroke key={j} d={d} i={9} />)}
      {g.header.map((d, j) => <Stroke key={j} d={d} i={10} />)}
      {g.cells.map((c, k) => (
        <g key={k}>
          <rect x={c.x + 3} y={c.y + 3} width={38} height={30} rx={3} className="cell" style={{ ["--i" as string]: bookOrder.indexOf(k) }} />
          {c.d.map((d, j) => <Stroke key={j} d={d} i={11} />)}
        </g>
      ))}
      <text x={850} y={380} textAnchor="middle" className="fill-ink font-hand" fontSize="28">calendar full of</text>
      <text x={850} y={412} textAnchor="middle" className="fill-ink font-hand" fontSize="28">booked appointments</text>
    </svg>
  );
}

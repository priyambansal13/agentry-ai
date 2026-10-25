"use client";

import { cn } from "@agentry/ui";
import rough from "roughjs";
import { useEffect, useMemo, useRef, useState } from "react";

const gen = rough.generator();
type Opts = { seed: number; fill?: boolean; roughness?: number };

/** Path data for a hand-drawn shape. A fixed seed gives identical strokes on server and client. */
function paths(drawable: ReturnType<typeof gen.rectangle>) {
  return gen.toPaths(drawable).map((p) => p.d);
}
export const sk = {
  rect: (x: number, y: number, w: number, h: number, o: Opts) =>
    paths(gen.rectangle(x, y, w, h, { seed: o.seed, roughness: o.roughness ?? 1.1, bowing: 1.2, ...(o.fill ? { fill: "#000", fillStyle: "solid" } : {}) })),
  line: (x1: number, y1: number, x2: number, y2: number, o: Opts) =>
    paths(gen.line(x1, y1, x2, y2, { seed: o.seed, roughness: o.roughness ?? 1, bowing: 2 })),
  polygon: (pts: [number, number][], o: Opts) =>
    paths(gen.polygon(pts, { seed: o.seed, roughness: o.roughness ?? 1.1, ...(o.fill ? { fill: "#000", fillStyle: "solid" } : {}) })),
};

/** Adds `drawn` once the figure is on screen; CSS then animates every stroke marked data-draw. */
export function useDrawOnView<T extends Element>() {
  const ref = useRef<T>(null);
  const [drawn, setDrawn] = useState(false);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const io = new IntersectionObserver(([e]) => e?.isIntersecting && (setDrawn(true), io.disconnect()), { threshold: 0.25 });
    io.observe(el);
    return () => io.disconnect();
  }, []);
  return { ref, drawn };
}

/** A stroke that draws itself. `i` staggers it. */
export function Stroke({ d, i = 0, className }: { d: string; i?: number; className?: string }) {
  return (
    <path d={d} data-draw pathLength={1} fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round"
      className={className} style={{ ["--i" as string]: i }} />
  );
}

type FlowProps = { steps: string[]; highlight?: number; seed?: number; className?: string; label: string };

/** A flow of hand-drawn boxes with arrows, as in the reference sketches: left-to-right from `sm` up,
 *  top-to-bottom on phones so the handwriting stays readable. */
export function SketchFlow(props: FlowProps) {
  return (
    <div className={props.className}>
      <FlowSvg {...props} direction="row" className="hidden sm:block" />
      <FlowSvg {...props} direction="column" className="sm:hidden" />
    </div>
  );
}

function FlowSvg({ steps, highlight, seed = 1, className, label, direction }: FlowProps & { direction: "row" | "column" }) {
  const { ref, drawn } = useDrawOnView<SVGSVGElement>();
  const row = direction === "row";
  const boxW = row ? 150 : 300, boxH = row ? 78 : 62, gap = row ? 46 : 36, pad = 6;
  const width = row ? steps.length * boxW + (steps.length - 1) * gap + pad * 2 : boxW + pad * 2;
  const height = row ? boxH + pad * 2 : steps.length * boxH + (steps.length - 1) * gap + pad * 2;
  const shapes = useMemo(() => steps.map((_, i) => {
    const x = row ? pad + i * (boxW + gap) : pad;
    const y = row ? pad : pad + i * (boxH + gap);
    // Arrow from this box to the next: along x for rows, along y for columns.
    const [ax1, ay1, ax2, ay2] = row
      ? [x + boxW + 8, y + boxH / 2, x + boxW + gap - 8, y + boxH / 2]
      : [x + boxW / 2, y + boxH + 6, x + boxW / 2, y + boxH + gap - 6];
    const head = row
      ? [[ax2 - 10, ay2 - 8], [ax2 - 10, ay2 + 8]]
      : [[ax2 - 8, ay2 - 10], [ax2 + 8, ay2 - 10]];
    return {
      x, y,
      box: sk.rect(x, y, boxW, boxH, { seed: seed * 10 + i }),
      fill: i === highlight ? sk.rect(x + 4, y + 4, boxW - 8, boxH - 8, { seed: seed * 10 + i + 5, fill: true, roughness: 0.6 }) : [],
      arrow: i < steps.length - 1 ? [
        ...sk.line(ax1, ay1, ax2, ay2, { seed: seed * 20 + i }),
        ...head.flatMap(([hx, hy], k) => sk.line(hx!, hy!, ax2, ay2, { seed: seed * 30 + i * 2 + k })),
      ] : [],
    };
  }), [steps, highlight, seed, row, boxW, boxH, gap]);

  return (
    <svg ref={ref} viewBox={`0 0 ${width} ${height}`} role="img" aria-label={label}
      className={cn("sketch w-full text-ink", drawn && "drawn", !row && "mx-auto max-w-xs", className)}>
      {shapes.map((s, i) => (
        <g key={i}>
          {s.fill.map((d, j) => <path key={`f${j}`} d={d} fill="var(--lime)" stroke="none" />)}
          {s.box.map((d, j) => <Stroke key={`b${j}`} d={d} i={i * 2} />)}
          {s.arrow.map((d, j) => <Stroke key={`a${j}`} d={d} i={i * 2 + 1} />)}
          <foreignObject x={s.x + 8} y={s.y + 6} width={boxW - 16} height={boxH - 12}>
            <div className={cn("flex h-full items-center justify-center text-center font-hand leading-[0.95]",
              row ? "text-[27px]" : "text-[26px]", i === highlight ? "text-lime-ink" : "text-ink")}>{steps[i]}</div>
          </foreignObject>
        </g>
      ))}
    </svg>
  );
}

/** Hand-drawn underline for a headline word. */
export function Scribble({ className, seed = 7 }: { className?: string; seed?: number }) {
  const { ref, drawn } = useDrawOnView<SVGSVGElement>();
  const d = useMemo(() => [...sk.line(4, 10, 196, 6, { seed, roughness: 2 }), ...sk.line(20, 15, 180, 12, { seed: seed + 1, roughness: 2 })], [seed]);
  return (
    <svg ref={ref} viewBox="0 0 200 20" preserveAspectRatio="none" aria-hidden="true" className={cn("sketch text-ink", drawn && "drawn", className)}>
      {d.map((p, i) => <Stroke key={i} d={p} i={i + 4} />)}
    </svg>
  );
}

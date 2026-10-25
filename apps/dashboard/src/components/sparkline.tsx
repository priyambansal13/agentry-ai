/** 2px single-series sparkline for stat tiles. Decorative: the tile's value and delta carry the numbers. */
export function Sparkline({ values, label }: { values: number[]; label: string }) {
  const w = 240;
  const h = 40;
  const max = Math.max(...values, 1);
  const step = values.length > 1 ? w / (values.length - 1) : w;
  const pts = values.map((v, i) => [i * step, h - 3 - (v / max) * (h - 6)] as const);
  const line = pts.map(([x, y], i) => `${i ? "L" : "M"}${x.toFixed(1)},${y.toFixed(1)}`).join(" ");
  const area = `${line} L${w},${h} L0,${h} Z`;
  const last = pts.at(-1);
  return (
    <svg viewBox={`0 0 ${w} ${h}`} preserveAspectRatio="none" className="h-10 w-full" role="img" aria-label={`${label}, last ${values.length} days`}>
      <path d={area} fill="var(--series-1-fill)" />
      <path d={line} fill="none" stroke="var(--series-1)" strokeWidth={2} vectorEffect="non-scaling-stroke" strokeLinejoin="round" strokeLinecap="round" />
      {last && <circle cx={last[0]} cy={last[1]} r={3} fill="var(--series-1)" stroke="var(--card)" strokeWidth={2} vectorEffect="non-scaling-stroke" />}
    </svg>
  );
}

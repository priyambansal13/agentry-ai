"use client";

import { Area, AreaChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

type Point = { day: string; value: number };

const compact = new Intl.NumberFormat("en-IN", { notation: "compact", maximumFractionDigits: 1 });

const fmtDay = (d: string) => new Date(`${d}T00:00:00`).toLocaleDateString("en-IN", { day: "numeric", month: "short" });

/** One series, one axis, recessive grid, crosshair tooltip. The title above names the series (no legend box).
 *  Straight segments, not smoothed curves: smoothing invents values between sparse days (e.g. payments). */
export function TrendChart({ data, format }: { data: Point[]; format: "count" | "currency"; currency?: string | null }) {
  return (
    <div className="h-64 w-full">
      <ResponsiveContainer>
        <AreaChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
          <CartesianGrid vertical={false} stroke="var(--grid)" />
          <XAxis dataKey="day" tickFormatter={fmtDay} tick={{ fill: "var(--muted)", fontSize: 12 }} axisLine={false} tickLine={false} minTickGap={32} />
          <YAxis tick={{ fill: "var(--muted)", fontSize: 12 }} axisLine={false} tickLine={false} width={48} allowDecimals={false} tickFormatter={(v: number) => compact.format(v)} />
          <Tooltip
            cursor={{ stroke: "var(--ink)", strokeWidth: 1, strokeDasharray: "3 3" }}
            content={({ active, payload, label }) =>
              active && payload?.length ? (
                <div className="rounded-xl border border-line bg-card-raised px-3 py-2 text-sm shadow-card">
                  <div className="font-semibold text-ink">{Number(payload[0]!.value).toLocaleString("en-IN")}</div>
                  <div className="text-xs text-muted">{fmtDay(String(label))}</div>
                </div>
              ) : null
            }
          />
          <Area type="linear" dataKey="value" stroke="var(--series-1)" strokeWidth={2} fill="var(--series-1-fill)" activeDot={{ r: 4, stroke: "var(--card)", strokeWidth: 2, fill: "var(--series-1)" }} />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}

"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { tehranDate, tehranTime } from "@/lib/fa";

export type Series = {
  name: string;
  /** CSS color, e.g. "var(--chart-1)" */
  color: string;
  values: number[];
  dashed?: boolean;
};

export type Marker = {
  ts: string;
  side: "buy" | "sell";
  label: string;
  /** a signal the risk manager blocked: drawn hollow */
  blocked?: boolean;
};

type Props = {
  x: string[]; // ISO timestamps (UTC)
  series: Series[];
  height?: number;
  format: (v: number) => string;
  /** fill under the first series down to `baseline` (used for drawdown) */
  area?: boolean;
  baseline?: number;
  ariaLabel: string;
  /** trade markers drawn on the first series (buy ▲ / sell ▼); hover shows their labels */
  markers?: Marker[];
};

const PAD = { top: 12, right: 8, bottom: 22, left: 8 };
const Y_TICKS = 3;

/**
 * Small dependency-free SVG line chart: one y-axis, thin 2px lines, recessive grid, crosshair + tooltip
 * listing every series, legend for >= 2 series and direct labels at the line ends, plus a table view.
 * Time runs left -> right even in RTL pages, which is the convention for price charts.
 */
export function LineChart({ x, series, height = 200, format, area = false, baseline, ariaLabel, markers = [] }: Props) {
  const wrap = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(340);
  const [hover, setHover] = useState<number | null>(null);

  useEffect(() => {
    const el = wrap.current;
    if (!el) return;
    const ro = new ResizeObserver(([e]) => setWidth(Math.max(240, Math.floor(e.contentRect.width))));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  const n = x.length;
  const { min, max } = useMemo(() => {
    let lo = Infinity;
    let hi = -Infinity;
    const all = series.flatMap((s) => s.values).filter(Number.isFinite);
    if (baseline !== undefined) all.push(baseline);
    for (const v of all) {
      lo = Math.min(lo, v);
      hi = Math.max(hi, v);
    }
    if (!Number.isFinite(lo)) return { min: 0, max: 1 };
    // A flat series (e.g. a bot that hasn't traded yet) gets a +/-0.5 % band, not a +/-1 unit one.
    const pad = Math.max((hi - lo) * 0.08, Math.abs(hi) * 0.005, 1e-9);
    return { min: lo - pad, max: hi + pad };
  }, [series, baseline]);

  // Place each marker on the last candle at or before its time (binary search on the time axis).
  const placed = useMemo(() => {
    const times = x.map((t) => Date.parse(t));
    const byIndex = new Map<number, Marker[]>();
    for (const m of markers) {
      const t = Date.parse(m.ts);
      let lo = 0;
      let hi = times.length - 1;
      if (!times.length || t < times[0]) continue;
      while (lo < hi) {
        const mid = (lo + hi + 1) >> 1;
        if (times[mid] <= t) lo = mid;
        else hi = mid - 1;
      }
      byIndex.set(lo, [...(byIndex.get(lo) ?? []), m]);
    }
    return byIndex;
  }, [x, markers]);

  if (n < 2) return <div className="py-8 text-center text-sm text-muted">دادهٔ کافی برای نمودار نیست.</div>;

  // reserve room on the right for direct labels when there are few series
  const labelRoom = series.length > 1 && series.length <= 4 ? 64 : 0;
  const innerW = width - PAD.left - PAD.right - labelRoom;
  const innerH = height - PAD.top - PAD.bottom;
  const sx = (i: number) => PAD.left + (i / (n - 1)) * innerW;
  const sy = (v: number) => PAD.top + (1 - (v - min) / (max - min)) * innerH;
  const path = (vals: number[]) => vals.map((v, i) => `${i ? "L" : "M"}${sx(i).toFixed(1)},${sy(v).toFixed(1)}`).join("");
  const ticks = Array.from({ length: Y_TICKS + 1 }, (_, i) => min + ((max - min) * i) / Y_TICKS);

  const onMove = (clientX: number) => {
    const rect = wrap.current?.getBoundingClientRect();
    if (!rect) return;
    const rel = (clientX - rect.left - PAD.left) / innerW;
    setHover(Math.min(n - 1, Math.max(0, Math.round(rel * (n - 1)))));
  };

  const tableStep = Math.max(1, Math.ceil(n / 12));
  const tableRows = x.map((t, i) => i).filter((i) => i % tableStep === 0 || i === n - 1);

  return (
    <figure className="w-full">
      {series.length > 1 && (
        <figcaption className="mb-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted">
          {series.map((s) => (
            <span key={s.name} className="inline-flex items-center gap-1.5">
              <svg width="18" height="6" aria-hidden>
                <line x1="1" y1="3" x2="17" y2="3" stroke={s.color} strokeWidth="2" strokeDasharray={s.dashed ? "4 3" : undefined} strokeLinecap="round" />
              </svg>
              {s.name}
            </span>
          ))}
        </figcaption>
      )}
      <div
        ref={wrap}
        dir="ltr"
        className="relative touch-pan-y select-none"
        onPointerMove={(e) => onMove(e.clientX)}
        onPointerDown={(e) => onMove(e.clientX)}
        onPointerLeave={() => setHover(null)}
      >
        <svg width={width} height={height} role="img" aria-label={ariaLabel} className="block">
          {ticks.map((t, i) => (
            <g key={i}>
              <line x1={PAD.left} x2={PAD.left + innerW} y1={sy(t)} y2={sy(t)} stroke="var(--border)" strokeWidth="1" />
            </g>
          ))}
          {area && series[0] && (
            <path
              d={`${path(series[0].values)}L${sx(n - 1)},${sy(baseline ?? min)}L${sx(0)},${sy(baseline ?? min)}Z`}
              fill={series[0].color}
              opacity="0.15"
            />
          )}
          {series.map((s) => (
            <path
              key={s.name}
              d={path(s.values)}
              fill="none"
              stroke={s.color}
              strokeWidth="2"
              strokeLinejoin="round"
              strokeLinecap="round"
              strokeDasharray={s.dashed ? "5 4" : undefined}
            />
          ))}
          {series[0] &&
            [...placed.entries()].map(([i, ms]) => {
              const m = ms[ms.length - 1];
              const cx = sx(i);
              const cy = sy(series[0].values[i]);
              const color = m.blocked ? "var(--muted)" : m.side === "buy" ? "var(--up)" : "var(--down)";
              const d = m.side === "buy" ? `M${cx},${cy + 5} l-5,9 h10 z` : `M${cx},${cy - 5} l-5,-9 h10 z`;
              return (
                <path
                  key={i}
                  d={d}
                  fill={m.blocked ? "var(--surface)" : color}
                  stroke={m.blocked ? color : "var(--surface)"}
                  strokeWidth={m.blocked ? 1.5 : 1}
                />
              );
            })}
          {/* Tick labels after the lines, with a halo, so a line never runs through a number. */}
          {ticks.map((t, i) => (
            <text
              key={i}
              x={PAD.left + 2}
              y={sy(t) - 3}
              fontSize="10"
              fill="var(--muted)"
              stroke="var(--surface)"
              strokeWidth="3"
              paintOrder="stroke"
              className="num"
            >
              {format(t)}
            </text>
          ))}
          {labelRoom > 0 &&
            series.map((s) => (
              <text key={s.name} x={sx(n - 1) + 6} y={sy(s.values[n - 1]) + 4} fontSize="10.5" fill="var(--text)" fontWeight="700">
                {s.name}
              </text>
            ))}
          <text x={PAD.left} y={height - 6} fontSize="10" fill="var(--muted)">
            {tehranDate(x[0])}
          </text>
          <text x={PAD.left + innerW} y={height - 6} fontSize="10" fill="var(--muted)" textAnchor="end">
            {tehranDate(x[n - 1])}
          </text>
          {hover !== null && (
            <g>
              <line x1={sx(hover)} x2={sx(hover)} y1={PAD.top} y2={PAD.top + innerH} stroke="var(--muted)" strokeWidth="1" />
              {series.map((s) => (
                <circle key={s.name} cx={sx(hover)} cy={sy(s.values[hover])} r="4" fill={s.color} stroke="var(--surface)" strokeWidth="2" />
              ))}
            </g>
          )}
        </svg>
        {hover !== null && (
          <div
            dir="rtl"
            className="pointer-events-none absolute top-1 z-10 min-w-36 rounded-lg border border-border bg-surface px-2.5 py-1.5 text-xs shadow-md"
            style={sx(hover) > width / 2 ? { left: 8 } : { right: 8 }}
          >
            <div className="mb-1 text-muted">{tehranTime(x[hover])}</div>
            {(placed.get(hover) ?? []).map((m, k) => (
              <div key={`m${k}`} className={`mb-1 max-w-56 leading-5 ${m.blocked ? "text-muted" : m.side === "buy" ? "text-up" : "text-down"}`}>
                {m.blocked ? "⛔ " : m.side === "buy" ? "▲ " : "▼ "}
                {m.label}
              </div>
            ))}
            {series.map((s) => (
              <div key={s.name} className="flex items-center justify-between gap-3">
                <span className="inline-flex items-center gap-1.5 text-muted">
                  <svg width="12" height="4" aria-hidden>
                    <line x1="1" y1="2" x2="11" y2="2" stroke={s.color} strokeWidth="2" strokeLinecap="round" />
                  </svg>
                  {s.name}
                </span>
                <b className="num text-text">{format(s.values[hover])}</b>
              </div>
            ))}
          </div>
        )}
      </div>
      <details className="mt-2 text-xs">
        <summary className="cursor-pointer text-muted">نمایش جدول داده‌ها</summary>
        <table className="mt-2 w-full text-right">
          <thead className="text-muted">
            <tr>
              <th className="py-1 font-normal">زمان</th>
              {series.map((s) => (
                <th key={s.name} className="py-1 font-normal">
                  {s.name}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {tableRows.map((i) => (
              <tr key={i} className="border-t border-border">
                <td className="py-1">{tehranTime(x[i])}</td>
                {series.map((s) => (
                  <td key={s.name} className="num py-1">
                    {format(s.values[i])}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </details>
    </figure>
  );
}

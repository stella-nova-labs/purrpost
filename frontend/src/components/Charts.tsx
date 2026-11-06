import { useState, type ReactNode } from 'react'

import { Card } from './ui'

const fmt = (n: number) => (n >= 10_000 ? `${Math.round(n / 1000)}K` : n.toLocaleString('ru-RU'))

/** A headline number: when one value is the answer, it's not a chart. */
export function StatTile({ label, value, hint }: { label: string; value: ReactNode; hint?: string }) {
  return (
    <Card className="flex flex-col gap-1 p-3.5">
      <span className="text-[12px] font-bold text-muted">{label}</span>
      <span className="font-display text-[22px] font-bold leading-tight">{value}</span>
      {hint && <span className="text-[11px] text-muted">{hint}</span>}
    </Card>
  )
}

function niceMax(v: number): number {
  if (v <= 0) return 1
  const p = 10 ** Math.floor(Math.log10(v))
  return [1, 2, 2.5, 5, 10].map((m) => m * p).find((x) => x >= v) ?? v
}

/** Tooltip over the plot; `pct` is the horizontal position in % of the chart width, kept inside the card. */
function Tip({ pct, children }: { pct: number; children: ReactNode }) {
  return (
    <div
      className="pointer-events-none absolute top-0 -translate-x-1/2 rounded-lg border border-line-2 bg-surface-2 px-2 py-1 text-[12px] whitespace-nowrap shadow-lg"
      style={{ left: `clamp(80px, ${pct}%, calc(100% - 80px))` }}
    >
      {children}
    </div>
  )
}

const W = 340
const H = 150
const PAD = { l: 34, r: 8, t: 26, b: 18 }

/** One series over time: 2px line, a 10% wash, an end dot with a surface ring, crosshair + tooltip. */
export function LineChart({ points, label }: { points: { x: string; y: number }[]; label: (p: { x: string; y: number }) => string }) {
  const [hover, setHover] = useState<number | null>(null)
  if (points.length === 0) return null
  const max = niceMax(Math.max(...points.map((p) => p.y)))
  const iw = W - PAD.l - PAD.r
  const ih = H - PAD.t - PAD.b
  const X = (i: number) => PAD.l + (points.length === 1 ? iw / 2 : (i / (points.length - 1)) * iw)
  const Y = (v: number) => PAD.t + ih - (v / max) * ih
  const d = points.map((p, i) => `${i ? 'L' : 'M'}${X(i)},${Y(p.y)}`).join(' ')
  const last = points.length - 1
  const pick = (clientX: number, rect: DOMRect) => {
    const rel = ((clientX - rect.left) / rect.width) * W
    setHover(Math.max(0, Math.min(last, Math.round(((rel - PAD.l) / iw) * last))))
  }
  const h = hover ?? last
  return (
    <div className="relative">
      <Tip pct={(X(h) / W) * 100}>
        {label(points[h])}
      </Tip>
      <svg
        viewBox={`0 0 ${W} ${H}`}
        className="w-full touch-none"
        role="img"
        onPointerMove={(e) => pick(e.clientX, e.currentTarget.getBoundingClientRect())}
        onPointerDown={(e) => pick(e.clientX, e.currentTarget.getBoundingClientRect())}
        onPointerLeave={() => setHover(null)}
      >
        {[0, 0.5, 1].map((f) => (
          <g key={f}>
            <line x1={PAD.l} x2={W - PAD.r} y1={Y(max * f)} y2={Y(max * f)} stroke="var(--color-line)" strokeWidth={1} />
            <text x={PAD.l - 6} y={Y(max * f) + 4} textAnchor="end" fontSize={10} fill="var(--color-muted)">
              {fmt(max * f)}
            </text>
          </g>
        ))}
        <path d={`${d} L${X(last)},${Y(0)} L${X(0)},${Y(0)} Z`} fill="var(--color-accent)" opacity={0.1} />
        <path d={d} fill="none" stroke="var(--color-accent)" strokeWidth={2} strokeLinejoin="round" strokeLinecap="round" />
        {hover !== null && <line x1={X(h)} x2={X(h)} y1={PAD.t} y2={PAD.t + ih} stroke="var(--color-line-2)" strokeWidth={1} />}
        <circle cx={X(h)} cy={Y(points[h].y)} r={4.5} fill="var(--color-accent)" stroke="var(--color-surface)" strokeWidth={2} />
        <text x={PAD.l} y={H - 4} fontSize={10} fill="var(--color-muted)">
          {points[0].x}
        </text>
        <text x={W - PAD.r} y={H - 4} fontSize={10} fill="var(--color-muted)" textAnchor="end">
          {points[last].x}
        </text>
      </svg>
    </div>
  )
}

/** Values per item (e.g. reach per post): columns <= 24px, 4px rounded caps, square at the baseline. */
export function ColumnChart({ items, onPick }: { items: { key: number; value: number; tip: string }[]; onPick?: (key: number) => void }) {
  const [hover, setHover] = useState<number | null>(null)
  if (items.length === 0) return null
  const max = niceMax(Math.max(...items.map((i) => i.value)))
  const iw = W - PAD.l - PAD.r
  const ih = H - PAD.t - PAD.b
  const band = iw / items.length
  const bw = Math.min(24, band - 2)
  const Y = (v: number) => PAD.t + ih - (v / max) * ih
  const top = items.reduce((a, b, i) => (b.value > items[a].value ? i : a), 0)
  const h = hover ?? top
  const r = 4
  return (
    <div className="relative">
      <Tip pct={((PAD.l + band * h + band / 2) / W) * 100}>
        {items[h].tip}
      </Tip>
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full" role="img" onPointerLeave={() => setHover(null)}>
        {[0, 0.5, 1].map((f) => (
          <g key={f}>
            <line x1={PAD.l} x2={W - PAD.r} y1={Y(max * f)} y2={Y(max * f)} stroke="var(--color-line)" strokeWidth={1} />
            <text x={PAD.l - 6} y={Y(max * f) + 4} textAnchor="end" fontSize={10} fill="var(--color-muted)">
              {fmt(max * f)}
            </text>
          </g>
        ))}
        {items.map((it, i) => {
          const x = PAD.l + band * i + (band - bw) / 2
          const y = Y(it.value)
          const hgt = PAD.t + ih - y
          const rr = Math.min(r, hgt, bw / 2)
          const path = `M${x},${PAD.t + ih} V${y + rr} Q${x},${y} ${x + rr},${y} H${x + bw - rr} Q${x + bw},${y} ${x + bw},${y + rr} V${PAD.t + ih} Z`
          return (
            <g key={it.key}>
              <path d={path} fill="var(--color-accent)" opacity={hover === null || hover === i ? 1 : 0.45} />
              {/* hit target: the whole band, taller than the mark */}
              <rect
                x={PAD.l + band * i}
                y={PAD.t}
                width={band}
                height={ih}
                fill="transparent"
                onPointerEnter={() => setHover(i)}
                onPointerDown={() => setHover(i)}
                onClick={() => onPick?.(it.key)}
                style={{ cursor: onPick ? 'pointer' : 'default' }}
              />
            </g>
          )
        })}
      </svg>
    </div>
  )
}

/** A ranking: horizontal bars, value at the tip, label above (text in ink, never in the bar color). */
export function RankBars({ rows }: { rows: { label: string; value: number; note?: string }[] }) {
  const max = Math.max(1, ...rows.map((r) => r.value))
  return (
    <div className="flex flex-col gap-3">
      {rows.map((r) => (
        <div key={r.label} className="flex flex-col gap-1">
          <div className="flex justify-between gap-2 text-[13px]">
            <span className="truncate font-bold">{r.label}</span>
            <span className="shrink-0 text-muted">{r.note}</span>
          </div>
          <div className="flex items-center gap-2">
            <div className="h-3 rounded-r-[4px] bg-accent" style={{ width: `${Math.max(2, (r.value / max) * 82)}%` }} />
            <span className="text-[12px] font-bold">{fmt(r.value)}</span>
          </div>
        </div>
      ))}
    </div>
  )
}

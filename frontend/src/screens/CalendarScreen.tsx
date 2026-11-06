import { useQuery } from '@tanstack/react-query'
import { useMemo, useState } from 'react'

import { DraftBadge } from '../components/DraftBadge'
import { Icon } from '../components/icons'
import { Card, ScreenTitle, Spinner } from '../components/ui'
import { t } from '../i18n'
import { getCalendar } from '../lib/api'
import { dayKey, timeText } from '../lib/format'
import { useNav } from '../store/nav'

const DOT: Record<string, string> = {
  pending_review: 'bg-accent',
  needs_review: 'bg-warn',
  scheduled: 'bg-ok',
  publishing: 'bg-ok',
  published: 'bg-ink',
  partially_published: 'bg-warn',
  failed: 'bg-bad',
  generating: 'bg-muted',
}

export function CalendarScreen() {
  const push = useNav((s) => s.push)
  const [month, setMonth] = useState(() => {
    const d = new Date()
    return new Date(d.getFullYear(), d.getMonth(), 1)
  })
  const [today] = useState(() => dayKey(Date.now()))
  const [picked, setPicked] = useState(today)
  const from = month.getTime()
  const to = new Date(month.getFullYear(), month.getMonth() + 1, 1).getTime()
  const q = useQuery({ queryKey: ['calendar', from], queryFn: () => getCalendar(from, to) })

  const byDay = useMemo(() => {
    const m: Record<string, { drafts: NonNullable<typeof q.data>['drafts']; planned: NonNullable<typeof q.data>['planned'] }> = {}
    for (const d of q.data?.drafts ?? []) (m[dayKey(d.slot_ms)] ??= { drafts: [], planned: [] }).drafts.push(d)
    for (const p of q.data?.planned ?? []) (m[dayKey(p.slot_ms)] ??= { drafts: [], planned: [] }).planned.push(p)
    return m
  }, [q.data])

  const lead = (month.getDay() + 6) % 7 // Monday first
  const days = new Date(month.getFullYear(), month.getMonth() + 1, 0).getDate()
  const cells = [...Array(lead).fill(null), ...Array.from({ length: days }, (_, i) => new Date(month.getFullYear(), month.getMonth(), i + 1))]
  const sel = byDay[picked]
  const title = month.toLocaleDateString('ru-RU', { month: 'long', year: 'numeric' })

  return (
    <div className="flex flex-col gap-4">
      <ScreenTitle title={t('cal.title')} />
      <Card className="flex flex-col gap-3 p-3">
        <div className="flex items-center justify-between px-1">
          <button type="button" aria-label="prev" className="press p-1.5" onClick={() => setMonth(new Date(month.getFullYear(), month.getMonth() - 1, 1))}>
            <Icon name="back" size={18} />
          </button>
          <span className="font-display text-[15px] font-bold capitalize">{title}</span>
          <button type="button" aria-label="next" className="press p-1.5" onClick={() => setMonth(new Date(month.getFullYear(), month.getMonth() + 1, 1))}>
            <Icon name="next" size={18} />
          </button>
        </div>
        <div className="grid grid-cols-7 gap-1 text-center text-[11px] font-bold text-muted">
          {[0, 1, 2, 3, 4, 5, 6].map((d) => (
            <span key={d}>{t(`weekday.${d}` as 'weekday.0')}</span>
          ))}
        </div>
        <div className="grid grid-cols-7 gap-1">
          {cells.map((c, i) => {
            if (!c) return <span key={i} />
            const k = dayKey(c.getTime())
            const info = byDay[k]
            const on = k === picked
            return (
              <button
                key={i}
                type="button"
                onClick={() => setPicked(k)}
                className={`flex aspect-square flex-col items-center justify-center gap-1 rounded-xl text-[13px] font-bold ${
                  on ? 'bg-accent text-ground' : k === today ? 'bg-surface-2 text-accent' : 'text-ink'
                }`}
              >
                {c.getDate()}
                <span className="flex h-1.5 gap-0.5">
                  {info?.drafts.slice(0, 3).map((d) => <span key={d.id} className={`h-1.5 w-1.5 rounded-full ${on ? 'bg-ground' : DOT[d.status] ?? 'bg-muted'}`} />)}
                  {!info?.drafts.length && info?.planned.length ? <span className={`h-1.5 w-1.5 rounded-full border ${on ? 'border-ground' : 'border-muted'}`} /> : null}
                </span>
              </button>
            )
          })}
        </div>
      </Card>
      {q.isLoading && <Spinner />}
      <div className="flex flex-col gap-2">
        {!sel && !q.isLoading && <div className="px-1 text-[13px] text-muted">{t('cal.nothing')}</div>}
        {sel?.drafts.map((d) => (
          <Card key={d.id} onClick={() => push({ name: 'draft', id: d.id })} className="flex items-center gap-3 p-2.5">
            {d.thumb ? <img src={d.thumb} alt="" className="aspect-[4/5] w-12 rounded-lg object-cover" /> : <span className="aspect-[4/5] w-12 rounded-lg bg-surface-2" />}
            <div className="flex min-w-0 flex-1 flex-col gap-0.5">
              <span className="text-[13px] font-bold">
                {timeText(d.slot_ms)} · {d.character.name}
              </span>
              <span className="truncate text-[12px] text-muted">{d.idea || d.rubric}</span>
            </div>
            <DraftBadge status={d.status} />
          </Card>
        ))}
        {sel?.planned.map((p) => (
          <div key={`${p.character.id}-${p.slot_ms}`} className="flex items-center gap-3 rounded-2xl border border-dashed border-line px-3 py-2.5 text-[13px] text-muted">
            <Icon name="clock" size={18} />
            <span>
              {timeText(p.slot_ms)} · {p.character.name} · {t('cal.planned')}
            </span>
          </div>
        ))}
      </div>
    </div>
  )
}

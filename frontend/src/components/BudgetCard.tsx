import { t } from '../i18n'
import type { Budget } from '../lib/api'
import { Card } from './ui'

export function BudgetCard({ b }: { b: Budget }) {
  const frac = b.limit > 0 ? Math.min(1, b.spent / b.limit) : 1
  const [y, m] = b.month.split('-')
  const month = new Date(Number(y), Number(m) - 1, 1).toLocaleDateString('ru-RU', { month: 'long' })
  return (
    <Card className="flex flex-col gap-2.5 p-4">
      <div className="flex items-baseline justify-between">
        <span className="text-[13px] font-bold text-muted">{t('profile.budget', { month })}</span>
        <span className="font-display text-[18px] font-bold">${b.remaining.toFixed(2)}</span>
      </div>
      <div className="h-2 overflow-hidden rounded bg-line">
        <div className={`h-full rounded ${b.exhausted ? 'bg-bad' : frac > 0.8 ? 'bg-warn' : 'bg-accent'}`} style={{ width: `${frac * 100}%` }} />
      </div>
      <div className="text-[12px] text-muted">{t('profile.spent', { spent: b.spent.toFixed(2), limit: b.limit.toFixed(2) })}</div>
      {b.spent_own_keys > 0 && <div className="text-[12px] text-muted">{t('profile.spentOwn', { v: b.spent_own_keys.toFixed(2) })}</div>}
      {b.exhausted && <div className="text-[13px] font-bold text-bad">{t('profile.exhausted')}</div>}
    </Card>
  )
}

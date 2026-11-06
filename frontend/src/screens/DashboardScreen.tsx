import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'

import { ColumnChart, LineChart, RankBars, StatTile } from '../components/Charts'
import { Icon } from '../components/icons'
import { Card, Empty, ScreenTitle, Section, Spinner } from '../components/ui'
import { t } from '../i18n'
import { getDashboard, listCharacters } from '../lib/api'
import { useNav } from '../store/nav'

const n = (v: number | null | undefined) => (v === null || v === undefined ? t('dash.na') : v.toLocaleString('ru-RU'))
const day = (ms: number) => new Date(ms).toLocaleDateString('ru-RU', { day: 'numeric', month: 'short' })

export function DashboardScreen() {
  const [cid, setCid] = useState<number | undefined>()
  const push = useNav((s) => s.push)
  const chars = useQuery({ queryKey: ['characters'], queryFn: listCharacters })
  const q = useQuery({ queryKey: ['dashboard', cid], queryFn: () => getDashboard(cid) })
  const d = q.data
  const followers = d ? Object.values(d.totals.followers).reduce((a, b) => a + (b ?? 0), 0) : 0
  const measured = (d?.posts ?? []).filter((p) => p.metrics).slice(0, 14).reverse()
  return (
    <div className="flex flex-col gap-4">
      <ScreenTitle title={t('dash.title')} />
      {/* filters: one row above the charts */}
      <div className="no-scrollbar -mx-4 flex gap-2 overflow-x-auto px-4">
        {[{ id: undefined, name: t('dash.all') }, ...(chars.data ?? []).filter((c) => c.status === 'ready')].map((c) => (
          <button
            key={c.id ?? 'all'}
            type="button"
            onClick={() => setCid(c.id)}
            className={`shrink-0 rounded-full px-3.5 py-1.5 text-[13px] font-bold ${cid === c.id ? 'bg-accent text-ground' : 'bg-surface-2 text-muted'}`}
          >
            {c.name}
          </button>
        ))}
      </div>
      {!d ? (
        <Spinner />
      ) : (
        <>
          <div className="grid grid-cols-2 gap-2">
            <StatTile
              label={t('dash.followers')}
              value={Object.keys(d.totals.followers).length ? n(followers) : t('dash.na')}
              hint={Object.entries(d.totals.followers).map(([k, v]) => `${t(`acc.${k}` as 'acc.instagram')}: ${n(v)}`).join(' · ') || undefined}
            />
            <StatTile label={t('dash.postsMonth')} value={n(d.totals.posts_month)} />
            <StatTile label={t('dash.avgReach')} value={n(d.totals.avg_reach)} />
            <StatTile label={t('dash.avgLikes')} value={n(d.totals.avg_likes)} />
          </div>
          <StatTile
            label={t('dash.spend')}
            value={`$${d.totals.spend_month.toFixed(2)}`}
            hint={t('profile.spent', { spent: d.budget.spent.toFixed(2), limit: d.budget.limit.toFixed(2) })}
          />
          {d.followers_series.length > 1 && (
            <Section title={t('dash.followersChart')}>
              <Card className="p-3 pt-10">
                <LineChart
                  points={d.followers_series.map((p) => ({ x: p.day.slice(5).split('-').reverse().join('.'), y: p.followers }))}
                  label={(p) => `${p.x}: ${p.y.toLocaleString('ru-RU')}`}
                />
              </Card>
            </Section>
          )}
          {measured.length > 0 && (
            <Section title={t('dash.reachChart')}>
              <Card className="p-3 pt-10">
                <ColumnChart
                  items={measured.map((p) => ({
                    key: p.id,
                    value: p.metrics!.reach,
                    tip: t('dash.reachTip', { date: day(p.published_ms), reach: n(p.metrics!.reach), likes: n(p.metrics!.likes) }),
                  }))}
                  onPick={(id) => push({ name: 'draft', id })}
                />
              </Card>
            </Section>
          )}
          {d.rubrics.length > 0 && (
            <Section title={t('dash.rubrics')}>
              <Card className="p-4">
                <RankBars
                  rows={d.rubrics.map((r) => ({ label: r.rubric || t('dash.noRubric'), value: r.avg_reach, note: t('dash.rubricNote', { n: r.posts, likes: n(r.avg_likes) }) }))}
                />
              </Card>
            </Section>
          )}
          <Section title={t('dash.posts')}>
            {d.posts.length === 0 && <Empty icon="chart" title={t('dash.empty')} text={t('dash.emptyText')} />}
            {/* the table view: every number the charts show */}
            <div className="flex flex-col gap-2">
              {d.posts.map((p) => (
                <Card key={p.id} onClick={() => push({ name: 'draft', id: p.id })} className="flex gap-3 p-2.5">
                  {p.thumb ? <img src={p.thumb} alt="" className="aspect-[4/5] w-14 shrink-0 rounded-lg object-cover" /> : null}
                  <div className="flex min-w-0 flex-1 flex-col gap-1">
                    <span className="truncate text-[13px] font-bold">
                      {p.character} · {day(p.published_ms)}
                    </span>
                    <span className="truncate text-[12px] text-muted">{p.rubric || p.idea}</span>
                    {p.metrics ? (
                      <span className="flex flex-wrap gap-x-3 gap-y-0.5 text-[12px]">
                        <span>👁 {n(p.metrics.reach)}</span>
                        <span>
                          <Icon name="heart" size={12} className="inline" /> {n(p.metrics.likes)}
                        </span>
                        <span>💬 {n(p.metrics.comments)}</span>
                        <span>🔖 {n(p.metrics.saves)}</span>
                        <span className="text-muted">{p.window === '7d' ? t('dash.window7') : t('dash.window24')}</span>
                      </span>
                    ) : (
                      <span className="text-[12px] text-muted">{t('dash.noMetrics')}</span>
                    )}
                  </div>
                </Card>
              ))}
            </div>
          </Section>
        </>
      )}
    </div>
  )
}

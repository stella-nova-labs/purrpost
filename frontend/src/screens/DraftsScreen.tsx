import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'

import { DraftBadge } from '../components/DraftBadge'
import { Icon } from '../components/icons'
import { Card, Empty, ScreenTitle, Segmented, Spinner } from '../components/ui'
import { t, type Key } from '../i18n'
import { type Draft, listDrafts } from '../lib/api'
import { slotText } from '../lib/format'
import { useNav } from '../store/nav'

type Filter = 'review' | 'scheduled' | 'published'
const STATUS: Record<Filter, string> = {
  review: 'generating,pending_review,needs_review,failed',
  scheduled: 'scheduled,publishing',
  published: 'published,partially_published',
}
const EMPTY: Record<Filter, Key> = { review: 'drafts.empty', scheduled: 'drafts.emptyScheduled', published: 'drafts.emptyPublished' }

export function DraftRow({ d }: { d: Draft }) {
  const push = useNav((s) => s.push)
  const first = d.slides[0]
  return (
    <Card onClick={() => push({ name: 'draft', id: d.id })} className="flex gap-3 p-2.5">
      <div className="relative aspect-[4/5] w-[76px] shrink-0 overflow-hidden rounded-xl bg-surface-2">
        {first ? (
          <img src={first.url} alt="" className="h-full w-full object-cover" loading="lazy" />
        ) : (
          <span className="flex h-full items-center justify-center">
            <Spinner size={18} />
          </span>
        )}
        {d.slides.length > 1 && (
          <span className="absolute top-1 right-1 rounded bg-ground/70 px-1 text-[10px] font-bold">{d.slides.length}</span>
        )}
      </div>
      <div className="flex min-w-0 flex-1 flex-col gap-1 py-0.5">
        <div className="flex items-center gap-2">
          <span className="truncate font-display text-[14px] font-bold">{d.character.name}</span>
          <DraftBadge status={d.status} />
        </div>
        <span className="text-[12px] text-muted">
          {slotText(d.slot_ms)}
          {d.rubric ? ` · ${d.rubric}` : ''}
        </span>
        <span className="line-clamp-2 text-[13px]">{d.idea || d.caption || '…'}</span>
      </div>
      <Icon name="next" size={18} className="self-center text-muted" />
    </Card>
  )
}

export function DraftsScreen() {
  const [f, setF] = useState<Filter>('review')
  const q = useQuery({
    queryKey: ['drafts', f],
    queryFn: () => listDrafts({ status: STATUS[f] }),
    refetchInterval: (query) => (query.state.data?.some((d) => d.status === 'generating' || d.status === 'publishing') ? 3000 : 20_000),
  })
  const rows = f === 'published' ? [...(q.data ?? [])].reverse() : q.data
  return (
    <div className="flex flex-col gap-4">
      <ScreenTitle title={t('drafts.title')} />
      <Segmented<Filter>
        value={f}
        onChange={setF}
        options={[
          ['review', t('drafts.review')],
          ['scheduled', t('drafts.scheduled')],
          ['published', t('drafts.published')],
        ]}
      />
      {q.isLoading && <Spinner />}
      {rows?.length === 0 && <Empty icon="drafts" title={t(EMPTY[f])} text={f === 'review' ? t('drafts.emptyText') : undefined} />}
      <div className="flex flex-col gap-2.5">
        {rows?.map((d) => (
          <DraftRow key={d.id} d={d} />
        ))}
      </div>
    </div>
  )
}

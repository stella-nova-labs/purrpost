import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Reorder } from 'framer-motion'
import { useState } from 'react'

import { DraftBadge } from '../components/DraftBadge'
import { Icon } from '../components/icons'
import { InstaPreview } from '../components/InstaPreview'
import { Button, Card, ErrorNote, Field, Input, ScreenTitle, Section, Spinner, TextArea } from '../components/ui'
import { errorText, t } from '../i18n'
import {
  approveDraft,
  type Draft,
  editDraft,
  errCode,
  getCharacter,
  getDraft,
  regenerateDraft,
  skipDraft,
  unscheduleDraft,
} from '../lib/api'
import { slotText } from '../lib/format'
import { confirmAction, haptic } from '../lib/telegram'

const EDITABLE = ['pending_review', 'needs_review', 'scheduled']
const REVIEW = ['pending_review', 'needs_review']

function Editor({ d, onSaved }: { d: Draft; onSaved: (d: Draft) => void }) {
  const [caption, setCaption] = useState(d.caption)
  const [tags, setTags] = useState(d.hashtags.join(' '))
  const [order, setOrder] = useState(d.slides.map((s) => s.index))
  const byIndex = Object.fromEntries(d.slides.map((s) => [s.index, s]))
  const save = useMutation({
    mutationFn: () => editDraft(d.id, { caption, hashtags: tags.split(/[\s,]+/).filter(Boolean), order }),
    onSuccess: onSaved,
  })
  const dirty = caption !== d.caption || tags !== d.hashtags.join(' ') || order.some((x, i) => x !== i)
  return (
    <Card className="flex flex-col gap-3 p-4">
      <Field label={t('draft.caption')}>
        <TextArea rows={5} value={caption} onChange={(e) => setCaption(e.target.value)} />
      </Field>
      <Field label={t('draft.hashtags')}>
        <Input value={tags} onChange={(e) => setTags(e.target.value)} />
      </Field>
      {d.slides.length > 1 && (
        <Field label={t('draft.order')}>
          <Reorder.Group axis="x" values={order} onReorder={setOrder} className="flex gap-2">
            {order.map((idx) => (
              <Reorder.Item key={idx} value={idx} className="aspect-[4/5] w-16 cursor-grab touch-none overflow-hidden rounded-lg active:cursor-grabbing">
                <img src={byIndex[idx].url} alt="" draggable={false} className="pointer-events-none h-full w-full object-cover" />
              </Reorder.Item>
            ))}
          </Reorder.Group>
        </Field>
      )}
      {save.isError && <ErrorNote text={errorText(errCode(save.error))} />}
      <Button kind="secondary" icon="check" disabled={!dirty || save.isPending} onClick={() => save.mutate()}>
        {t('draft.saveEdits')}
      </Button>
    </Card>
  )
}

export function DraftScreen({ id }: { id: number }) {
  const qc = useQueryClient()
  const q = useQuery({
    queryKey: ['draft', id],
    queryFn: () => getDraft(id),
    refetchInterval: (query) => (['generating', 'publishing'].includes(query.state.data?.status ?? '') ? 2500 : false),
  })
  const d = q.data
  const ch = useQuery({ queryKey: ['character', d?.character.id], queryFn: () => getCharacter(d!.character.id), enabled: !!d })
  const onDraft = (nd: Draft) => {
    qc.setQueryData(['draft', id], nd)
    void qc.invalidateQueries({ queryKey: ['drafts'] })
    void qc.invalidateQueries({ queryKey: ['calendar'] })
  }
  const act = useMutation({ mutationFn: (fn: () => Promise<Draft>) => fn(), onSuccess: onDraft })
  if (!d) return <Spinner />
  const issues = d.slides.filter((s) => !s.ok && s.issues.length)
  return (
    <div className="flex flex-col gap-4">
      <ScreenTitle title={d.character.name} subtitle={t('draft.for', { when: slotText(d.slot_ms) })} back right={<DraftBadge status={d.status} />} />
      {d.status === 'generating' || !d.slides.length ? (
        d.status === 'failed' ? (
          <ErrorNote text={errorText(d.error ?? 'generic')} />
        ) : (
          <Card className="flex items-center gap-3 p-4">
            <Spinner />
            <span className="text-[14px] text-muted">{t('draft.generating')}</span>
          </Card>
        )
      ) : (
        <InstaPreview handle={d.character.handle} avatar={ch.data?.avatar ?? null} slides={d.slides} caption={d.final_caption} />
      )}
      {d.status === 'failed' && d.slides.length > 0 && <ErrorNote text={errorText(d.error ?? 'generic')} />}
      {!d.qa_ok && d.slides.length > 0 && d.status !== 'generating' && (
        <Card className="flex flex-col gap-1.5 border-warn/40 bg-warn-deep p-3.5 text-[13px] text-warn">
          <span className="font-bold">{t('draft.qaWarn')}</span>
          {issues.map((s) => (
            <span key={s.index}>{t('draft.slideIssues', { n: s.index + 1, issues: s.issues.join('; ') })}</span>
          ))}
        </Card>
      )}
      {act.isError && <ErrorNote text={errorText(errCode(act.error))} />}
      {REVIEW.includes(d.status) && (
        <Button
          kind="ok"
          icon="check"
          disabled={act.isPending}
          onClick={() => {
            haptic('medium')
            act.mutate(() => approveDraft(d.id))
          }}
        >
          {t('draft.approve')}
        </Button>
      )}
      {d.status === 'scheduled' && (
        <Button kind="secondary" icon="back" disabled={act.isPending} onClick={() => act.mutate(() => unscheduleDraft(d.id))}>
          {t('draft.unschedule')}
        </Button>
      )}
      {[...EDITABLE, 'failed'].includes(d.status) && (
        <div className="grid grid-cols-2 gap-2">
          <Button
            kind="secondary"
            icon="refresh"
            small
            disabled={act.isPending}
            onClick={async () => (await confirmAction(t('draft.regenConfirm'))) && act.mutate(() => regenerateDraft(d.id, 'all'))}
          >
            {t('draft.regenAll')}
          </Button>
          <Button kind="secondary" icon="image" small disabled={act.isPending || !d.slides.length} onClick={() => act.mutate(() => regenerateDraft(d.id, 'images'))}>
            {t('draft.regenImages')}
          </Button>
        </div>
      )}
      {EDITABLE.includes(d.status) && (
        <Section title={t('draft.edit')}>
          <Editor key={`${d.caption}|${d.hashtags.join()}|${d.slides.map((s) => s.url).join()}`} d={d} onSaved={onDraft} />
        </Section>
      )}
      {d.idea && (
        <Card className="flex gap-2 p-3.5 text-[13px] text-muted">
          <Icon name="sparkle" size={16} className="mt-0.5 shrink-0" />
          <span>
            {d.rubric ? <b className="text-ink">{d.rubric}. </b> : null}
            {d.idea}
          </span>
        </Card>
      )}
      {[...EDITABLE, 'failed'].includes(d.status) && (
        <Button kind="ghost" icon="trash" disabled={act.isPending} onClick={async () => (await confirmAction(t('draft.skipConfirm'))) && act.mutate(() => skipDraft(d.id))}>
          {t('draft.skip')}
        </Button>
      )}
    </div>
  )
}

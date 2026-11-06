import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'

import { AccountsCard } from '../components/AccountsCard'
import { Icon } from '../components/icons'
import { Button, Card, ErrorNote, Field, Input, ScreenTitle, Section, Spinner, Toggle } from '../components/ui'
import { errorText, t } from '../i18n'
import { archiveCharacter, type Character, errCode, generateNow, getCharacter, patchSettings, type Schedule, type SettingsPatch } from '../lib/api'
import { confirmAction } from '../lib/telegram'
import { useNav } from '../store/nav'
import { Avatar, StatusBadge } from './CharactersScreen'

const TIMEZONES = [
  'America/New_York',
  'America/Chicago',
  'America/Los_Angeles',
  'America/Sao_Paulo',
  'Europe/London',
  'Europe/Berlin',
  'Europe/Moscow',
  'Asia/Dubai',
  'Asia/Tokyo',
  'Australia/Sydney',
  'UTC',
]
const SELECT = 'w-full rounded-xl border border-line bg-surface-2 px-3 py-2.5 text-[15px] outline-none focus:border-accent'

function useSettings(ch: Character) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: SettingsPatch) => patchSettings(ch.id, body),
    onSuccess: (c) => qc.setQueryData(['character', ch.id], c),
  })
}

function ScheduleCard({ ch }: { ch: Character }) {
  const [sc, setSc] = useState<Schedule>(ch.schedule)
  const save = useSettings(ch)
  const dirty = JSON.stringify(sc) !== JSON.stringify(ch.schedule)
  const toggleDay = (d: number) => setSc({ ...sc, days: sc.days.includes(d) ? sc.days.filter((x) => x !== d) : [...sc.days, d].sort() })
  const tzs = TIMEZONES.includes(sc.tz) ? TIMEZONES : [sc.tz, ...TIMEZONES]
  return (
    <Card className="flex flex-col gap-3 p-4">
      <Field label={t('char.times')}>
        <div className="flex flex-wrap gap-2">
          {sc.times.map((tm, i) => (
            <div key={i} className="flex items-center gap-1 rounded-xl border border-line bg-surface-2 pr-1">
              <input
                type="time"
                value={tm}
                onChange={(e) => setSc({ ...sc, times: sc.times.map((x, j) => (j === i ? e.target.value : x)) })}
                className="bg-transparent px-2 py-2 text-[15px] outline-none"
              />
              <button type="button" aria-label={t('common.delete')} className="text-muted" onClick={() => setSc({ ...sc, times: sc.times.filter((_, j) => j !== i) })}>
                <Icon name="skip" size={14} />
              </button>
            </div>
          ))}
          {sc.times.length < 6 && (
            <Button small kind="secondary" icon="plus" onClick={() => setSc({ ...sc, times: [...sc.times, '12:00'] })}>
              {t('char.addTime')}
            </Button>
          )}
        </div>
      </Field>
      <Field label={t('char.days')}>
        <div className="grid grid-cols-7 gap-1">
          {[0, 1, 2, 3, 4, 5, 6].map((d) => (
            <button
              key={d}
              type="button"
              onClick={() => toggleDay(d)}
              className={`rounded-lg py-2 text-[12px] font-bold ${sc.days.includes(d) ? 'bg-accent text-ground' : 'bg-surface-2 text-muted'}`}
            >
              {t(`weekday.${d}` as 'weekday.0')}
            </button>
          ))}
        </div>
      </Field>
      <div className="grid grid-cols-[2fr_1fr] gap-2">
        <Field label={t('char.tz')}>
          <select className={SELECT} value={sc.tz} onChange={(e) => setSc({ ...sc, tz: e.target.value })}>
            {tzs.map((z) => (
              <option key={z} value={z}>
                {z}
              </option>
            ))}
          </select>
        </Field>
        <Field label={t('char.lead')}>
          <Input inputMode="numeric" value={sc.lead_hours} onChange={(e) => setSc({ ...sc, lead_hours: Number(e.target.value.replace(/\D/g, '')) || 1 })} />
        </Field>
      </div>
      {save.isError && <ErrorNote text={errorText(errCode(save.error))} />}
      {dirty && (
        <Button onClick={() => save.mutate({ schedule: sc })} disabled={save.isPending}>
          {t('common.save')}
        </Button>
      )}
    </Card>
  )
}

function PostingCard({ ch }: { ch: Character }) {
  const save = useSettings(ch)
  const [text, setText] = useState(ch.disclosure_text)
  return (
    <Card className="flex flex-col gap-4 p-4">
      <Field label={t('char.slides')}>
        <div className="grid grid-cols-5 gap-1">
          {[1, 2, 3, 4, 5].map((n) => (
            <button
              key={n}
              type="button"
              onClick={() => save.mutate({ slides_max: n })}
              className={`rounded-lg py-2 text-[14px] font-bold ${ch.slides_max === n ? 'bg-accent text-ground' : 'bg-surface-2 text-muted'}`}
            >
              {n}
            </button>
          ))}
        </div>
      </Field>
      <Toggle on={ch.ai_disclosure} onChange={(v) => save.mutate({ ai_disclosure: v })} label={t('char.disclosure')} hint={t('char.disclosureHint')} />
      {ch.ai_disclosure && (
        <Field label={t('char.disclosureText')}>
          <Input value={text} onChange={(e) => setText(e.target.value)} onBlur={() => text !== ch.disclosure_text && save.mutate({ disclosure_text: text })} />
        </Field>
      )}
    </Card>
  )
}

function GenerateCard({ ch }: { ch: Character }) {
  const qc = useQueryClient()
  const [trend, setTrend] = useState(ch.trend)
  const save = useSettings(ch)
  const gen = useMutation({
    mutationFn: () => generateNow(ch.id, trend),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ['drafts'] }),
  })
  return (
    <Card className="flex flex-col gap-3 p-4">
      <Field label={t('char.trend')} hint={t('char.trendHint')}>
        <Input
          value={trend}
          placeholder={t('char.trendPh')}
          onChange={(e) => setTrend(e.target.value)}
          onBlur={() => trend !== ch.trend && save.mutate({ trend })}
        />
      </Field>
      <Button icon="sparkle" onClick={() => gen.mutate()} disabled={gen.isPending}>
        {t('char.generate')}
      </Button>
      {gen.isSuccess && <div className="text-[13px] text-ok">{t('char.generated')}</div>}
      {gen.isError && <ErrorNote text={errorText(errCode(gen.error))} />}
    </Card>
  )
}

export function CharacterScreen({ id }: { id: number }) {
  const q = useQuery({ queryKey: ['character', id], queryFn: () => getCharacter(id) })
  const push = useNav((s) => s.push)
  const pop = useNav((s) => s.pop)
  const qc = useQueryClient()
  const archive = useMutation({
    mutationFn: () => archiveCharacter(id),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['characters'] })
      pop()
    },
  })
  const ch = q.data
  if (!ch) return <Spinner />
  return (
    <div className="flex flex-col gap-5">
      <ScreenTitle title={ch.name} subtitle={`@${ch.handle}`} back />
      <Card className="flex items-center gap-3 p-4">
        <Avatar src={ch.avatar} size={64} />
        <div className="flex min-w-0 flex-1 flex-col gap-1.5">
          <StatusBadge c={ch} />
          <p className="m-0 line-clamp-3 text-[13px] text-muted">{ch.card.personality}</p>
        </div>
      </Card>
      <GenerateCard ch={ch} />
      <Section title={t('acc.title')}>
        <AccountsCard cid={ch.id} />
      </Section>
      <Section title={t('char.schedule')}>
        <ScheduleCard ch={ch} />
        <PostingCard ch={ch} />
      </Section>
      {ch.lore.length > 0 && (
        <Section title={t('char.lore')}>
          <Card className="flex flex-col divide-y divide-line">
            {[...ch.lore].reverse().map((l, i) => (
              <div key={i} className="flex flex-col gap-0.5 px-4 py-2.5">
                <span className="text-[11px] font-bold text-muted">
                  {l.date}
                  {l.rubric ? ` · ${l.rubric}` : ''}
                </span>
                <span className="text-[13px]">{l.summary}</span>
              </div>
            ))}
          </Card>
        </Section>
      )}
      {ch.card.notes && (
        <Section title={t('char.notes')}>
          <Card className="p-4 text-[13px] text-muted">{ch.card.notes}</Card>
        </Section>
      )}
      <div className="flex flex-col gap-2">
        <Button kind="secondary" icon="edit" onClick={() => push({ name: 'wizard', id: ch.id })}>
          {t('char.editWizard')}
        </Button>
        <Button kind="danger" icon="trash" onClick={async () => (await confirmAction(t('char.archiveConfirm'))) && archive.mutate()}>
          {t('char.archive')}
        </Button>
      </div>
    </div>
  )
}

import { t } from '../i18n'
import type { CardData, Rubric } from '../lib/api'
import { Icon } from './icons'
import { Button, Card, Field, Input, TextArea } from './ui'

const LANGS: [string, string][] = [
  ['en', 'English'],
  ['ru', 'Русский'],
  ['es', 'Español'],
  ['de', 'Deutsch'],
  ['fr', 'Français'],
  ['it', 'Italiano'],
  ['pt', 'Português'],
]

const SELECT = 'w-full rounded-xl border border-line bg-surface-2 px-3 py-2.5 text-[15px] outline-none focus:border-accent'

function RubricRow({ r, onChange, onRemove }: { r: Rubric; onChange: (r: Rubric) => void; onRemove: () => void }) {
  return (
    <div className="flex flex-col gap-2 rounded-xl border border-line bg-surface-2/50 p-3">
      <div className="flex gap-2">
        <select
          className={`${SELECT} w-28 shrink-0`}
          value={r.weekday ?? ''}
          onChange={(e) => onChange({ ...r, weekday: e.target.value === '' ? null : Number(e.target.value) })}
        >
          <option value="">{t('wiz.anyDay')}</option>
          {[0, 1, 2, 3, 4, 5, 6].map((d) => (
            <option key={d} value={d}>
              {t(`weekday.${d}` as 'weekday.0')}
            </option>
          ))}
        </select>
        <Input value={r.title} placeholder={t('wiz.rubricTitle')} onChange={(e) => onChange({ ...r, title: e.target.value })} />
        <button type="button" aria-label={t('common.delete')} onClick={onRemove} className="press shrink-0 px-1 text-muted">
          <Icon name="trash" size={18} />
        </button>
      </div>
      <Input value={r.description} placeholder={t('wiz.rubricDesc')} onChange={(e) => onChange({ ...r, description: e.target.value })} />
    </div>
  )
}

export function CardForm({ value, onChange }: { value: CardData; onChange: (c: CardData) => void }) {
  const set = <K extends keyof CardData>(k: K, v: CardData[K]) => onChange({ ...value, [k]: v })
  const setLook = (k: keyof CardData['appearance'], v: string) => onChange({ ...value, appearance: { ...value.appearance, [k]: v } })
  return (
    <div className="flex flex-col gap-4">
      <Card className="flex flex-col gap-3 p-4">
        <div className="grid grid-cols-2 gap-2">
          <Field label={t('wiz.name')}>
            <Input value={value.name} onChange={(e) => set('name', e.target.value)} />
          </Field>
          <Field label={t('wiz.handle')}>
            <Input value={value.handle} onChange={(e) => set('handle', e.target.value.toLowerCase())} placeholder="don.whiskers" />
          </Field>
        </div>
        <Field label={t('wiz.personality')}>
          <TextArea rows={4} value={value.personality} onChange={(e) => set('personality', e.target.value)} />
        </Field>
        <Field label={t('wiz.pain')}>
          <TextArea rows={2} value={value.pain} onChange={(e) => set('pain', e.target.value)} />
        </Field>
        <div className="grid grid-cols-[2fr_1fr] gap-2">
          <Field label={t('wiz.humor')}>
            <Input value={value.humor} onChange={(e) => set('humor', e.target.value)} />
          </Field>
          <Field label={t('wiz.language')}>
            <select className={SELECT} value={value.language} onChange={(e) => set('language', e.target.value)}>
              {LANGS.map(([v, l]) => (
                <option key={v} value={v}>
                  {l}
                </option>
              ))}
            </select>
          </Field>
        </div>
      </Card>
      <Card className="flex flex-col gap-3 p-4">
        <div className="font-display text-[14px] font-bold">{t('wiz.looks')}</div>
        <div className="grid grid-cols-2 gap-2">
          <Field label={t('wiz.breed')}>
            <Input value={value.appearance.breed} onChange={(e) => setLook('breed', e.target.value)} />
          </Field>
          <Field label={t('wiz.color')}>
            <Input value={value.appearance.color} onChange={(e) => setLook('color', e.target.value)} />
          </Field>
        </div>
        <Field label={t('wiz.marks')}>
          <Input value={value.appearance.marks} onChange={(e) => setLook('marks', e.target.value)} />
        </Field>
        <Field label={t('wiz.signature')}>
          <Input value={value.appearance.signature} onChange={(e) => setLook('signature', e.target.value)} />
        </Field>
      </Card>
      <Card className="flex flex-col gap-3 p-4">
        <div className="font-display text-[14px] font-bold">{t('wiz.rubrics')}</div>
        {value.rubrics.map((r, i) => (
          <RubricRow
            key={i}
            r={r}
            onChange={(nr) => set('rubrics', value.rubrics.map((x, j) => (j === i ? nr : x)))}
            onRemove={() => set('rubrics', value.rubrics.filter((_, j) => j !== i))}
          />
        ))}
        <Button kind="secondary" small icon="plus" onClick={() => set('rubrics', [...value.rubrics, { weekday: null, title: '', description: '' }])}>
          {t('wiz.addRubric')}
        </Button>
        <Field label={t('wiz.stop')}>
          <Input
            value={value.stop_topics.join(', ')}
            onChange={(e) => set('stop_topics', e.target.value.split(',').map((x) => x.trimStart()))}
          />
        </Field>
        <Field label={t('wiz.notes')}>
          <TextArea rows={3} value={value.notes} onChange={(e) => set('notes', e.target.value)} />
        </Field>
      </Card>
    </div>
  )
}

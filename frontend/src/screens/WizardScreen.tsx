import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { motion } from 'framer-motion'
import { useState } from 'react'

import { CardForm } from '../components/CardForm'
import { Icon } from '../components/icons'
import { ImageGrid } from '../components/ImageGrid'
import { Stepper } from '../components/Stepper'
import { Button, Card, ErrorNote, Field, Input, ScreenTitle, Spinner } from '../components/ui'
import { errorText, t } from '../i18n'
import {
  type CardData,
  type Character,
  chooseCandidate,
  confirmLora,
  createCharacter,
  deleteImage,
  errCode,
  getCharacter,
  putCard,
  requestCandidates,
  requestRefsheet,
  startTraining,
  suggestCard,
} from '../lib/api'
import { EMPTY_CARD } from '../lib/card'
import { confirmAction, haptic } from '../lib/telegram'
import { useNav } from '../store/nav'

const STEP_OF: Record<string, number> = { appearance: 1, refsheet: 2, training: 3, testing: 4, ready: 5 }

function Busy({ text }: { text: string }) {
  return (
    <Card className="flex items-center gap-3 p-4">
      <Spinner />
      <span className="text-[14px] text-muted">{text}</span>
    </Card>
  )
}

function useCharMutation<A>(id: number, fn: (a: A) => Promise<Character>) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: fn,
    onSuccess: (c) => {
      qc.setQueryData(['character', id], c)
      void qc.invalidateQueries({ queryKey: ['characters'] })
    },
  })
}

// ---------- step 1 for a new character ----------

function NewCard() {
  const [idea, setIdea] = useState('')
  const [card, setCard] = useState<CardData>(EMPTY_CARD)
  const replace = useNav((s) => s.replace)
  const qc = useQueryClient()
  const suggest = useMutation({ mutationFn: () => suggestCard(idea), onSuccess: (c) => setCard({ ...EMPTY_CARD, ...c }) })
  const create = useMutation({
    mutationFn: async () => {
      const c = await createCharacter({ ...card, stop_topics: card.stop_topics.filter(Boolean) })
      return requestCandidates(c.id, 8, '')
    },
    onSuccess: (c) => {
      qc.setQueryData(['character', c.id], c)
      void qc.invalidateQueries({ queryKey: ['characters'] })
      replace({ name: 'wizard', id: c.id })
    },
  })
  const err = suggest.error ?? create.error
  return (
    <div className="flex flex-col gap-4">
      <ScreenTitle title={t('wiz.title')} back />
      <Stepper step={0} maxStep={0} />
      <Card className="flex flex-col gap-3 p-4">
        <Field label={t('wiz.idea')} hint={t('wiz.suggestHint')}>
          <Input value={idea} onChange={(e) => setIdea(e.target.value)} placeholder={t('wiz.ideaPh')} />
        </Field>
        <Button icon="sparkle" kind="secondary" disabled={idea.trim().length < 3 || suggest.isPending} onClick={() => suggest.mutate()}>
          {suggest.isPending ? <Spinner size={16} /> : t('wiz.suggest')}
        </Button>
      </Card>
      {err && <ErrorNote text={errorText(errCode(err))} />}
      <CardForm value={card} onChange={setCard} />
      <Button disabled={!card.name.trim() || !card.handle.trim() || create.isPending} onClick={() => create.mutate()}>
        {t('wiz.saveCard')}
      </Button>
    </div>
  )
}

// ---------- steps for an existing character ----------

function EditCard({ ch }: { ch: Character }) {
  const [card, setCard] = useState<CardData>(ch.card)
  const save = useCharMutation(ch.id, () => putCard(ch.id, { ...card, stop_topics: card.stop_topics.filter(Boolean) }))
  return (
    <div className="flex flex-col gap-4">
      <CardForm value={card} onChange={setCard} />
      {save.isError && <ErrorNote text={errorText(errCode(save.error))} />}
      <Button disabled={save.isPending} onClick={() => save.mutate(undefined)}>
        {save.isSuccess ? t('common.saved') : t('wiz.saveOnly')}
      </Button>
    </div>
  )
}

function Candidates({ ch }: { ch: Character }) {
  const [extra, setExtra] = useState('')
  const more = useCharMutation(ch.id, () => requestCandidates(ch.id, 8, extra))
  const choose = useCharMutation(ch.id, (imageId: number) => chooseCandidate(ch.id, imageId))
  const busy = ch.busy.includes('candidates')
  const err = more.error ?? choose.error
  return (
    <div className="flex flex-col gap-4">
      <p className="m-0 text-[14px] text-muted">{t('wiz.candidatesText')}</p>
      {ch.candidates.length > 0 && (
        <ImageGrid
          images={[...ch.candidates].reverse()}
          cols={2}
          aspect="1/1"
          selected={ch.chosen_image_id}
          onPick={async (img) => {
            haptic()
            if (await confirmAction(t('wiz.choose'))) choose.mutate(img.id)
          }}
        />
      )}
      {busy && <Busy text={t('wiz.generating')} />}
      {err && <ErrorNote text={errorText(errCode(err))} />}
      <Card className="flex flex-col gap-3 p-4">
        <Input value={extra} onChange={(e) => setExtra(e.target.value)} placeholder={t('wiz.extraPh')} />
        <Button kind="secondary" icon="refresh" disabled={busy || more.isPending} onClick={() => more.mutate(undefined)}>
          {ch.candidates.length ? t('wiz.more') : t('wiz.generate')}
        </Button>
      </Card>
    </div>
  )
}

function Refs({ ch }: { ch: Character }) {
  const del = useCharMutation(ch.id, (imageId: number) => deleteImage(ch.id, imageId))
  const redo = useCharMutation(ch.id, () => requestRefsheet(ch.id, 16))
  const train = useCharMutation(ch.id, () => startTraining(ch.id))
  const busy = ch.busy.includes('refsheet')
  const err = del.error ?? redo.error ?? train.error
  return (
    <div className="flex flex-col gap-4">
      <p className="m-0 text-[14px] text-muted">{t('wiz.refsText', { min: ch.min_refs })}</p>
      {ch.training_error && <ErrorNote text={t('wiz.trainingError', { err: ch.training_error })} />}
      {busy && <Busy text={t('wiz.refsProgress', { n: ch.refs.length, total: 16 })} />}
      <ImageGrid images={ch.refs} cols={3} onDelete={busy ? undefined : (img) => del.mutate(img.id)} />
      {err && <ErrorNote text={errorText(errCode(err))} />}
      <div className="flex flex-col gap-2">
        <Button icon="sparkle" disabled={busy || ch.refs.length < ch.min_refs || train.isPending || ch.busy.includes('train')} onClick={() => train.mutate(undefined)}>
          {t('wiz.train', { n: ch.refs.length })}
        </Button>
        <Button kind="secondary" icon="refresh" disabled={busy || redo.isPending} onClick={() => redo.mutate(undefined)}>
          {t('wiz.redoRefs')}
        </Button>
      </div>
    </div>
  )
}

function Training() {
  return (
    <Card className="flex flex-col items-center gap-4 px-6 py-10 text-center">
      <motion.div animate={{ rotate: [0, 8, -8, 0], y: [0, -6, 0] }} transition={{ repeat: Infinity, duration: 2.2 }} className="text-accent">
        <Icon name="cat" size={56} />
      </motion.div>
      <div className="font-display text-[17px] font-bold">{t('wiz.trainingTitle')}</div>
      <p className="m-0 text-[14px] text-muted">{t('wiz.trainingText')}</p>
      <Spinner />
    </Card>
  )
}

function Testing({ ch }: { ch: Character }) {
  const confirm = useCharMutation(ch.id, (ok: boolean) => confirmLora(ch.id, ok))
  if (!ch.tests.length) return <Busy text={t('wiz.testing')} />
  return (
    <div className="flex flex-col gap-4">
      <p className="m-0 text-[14px] text-muted">{t('wiz.testText')}</p>
      <ImageGrid images={ch.tests} cols={2} />
      {confirm.isError && <ErrorNote text={errorText(errCode(confirm.error))} />}
      <Button kind="ok" icon="check" disabled={confirm.isPending} onClick={() => confirm.mutate(true)}>
        {t('wiz.itsHim')}
      </Button>
      <Button kind="secondary" icon="refresh" disabled={confirm.isPending} onClick={() => confirm.mutate(false)}>
        {t('wiz.retrain')}
      </Button>
    </div>
  )
}

function Done({ ch }: { ch: Character }) {
  const replace = useNav((s) => s.replace)
  return (
    <Card className="flex flex-col items-center gap-3 px-6 py-8 text-center">
      {ch.avatar && <img src={ch.avatar} alt="" className="h-24 w-24 rounded-full object-cover" />}
      <div className="font-display text-[18px] font-bold">{t('wiz.done')}</div>
      <p className="m-0 text-[14px] text-muted">{t('wiz.doneText')}</p>
      <Button onClick={() => replace({ name: 'character', id: ch.id })}>{t('wiz.open')}</Button>
    </Card>
  )
}

function ExistingWizard({ id }: { id: number }) {
  const q = useQuery({
    queryKey: ['character', id],
    queryFn: () => getCharacter(id),
    refetchInterval: (query) => {
      const c = query.state.data
      return c && (c.busy.length || c.status === 'training') ? 2500 : false
    },
  })
  const ch = q.data
  const maxStep = ch ? STEP_OF[ch.status] : 0
  // a step the user picked; forgotten as soon as the character moves to another stage
  const [picked, setPicked] = useState<{ step: number; at: number } | null>(null)
  const step = picked && picked.at === maxStep ? picked.step : null
  const setStep = (i: number) => setPicked({ step: i, at: maxStep })
  if (!ch) return <Spinner />
  const view = step ?? Math.min(maxStep, 4)
  const failed = ch.last_job?.status === 'failed' && !ch.busy.length ? ch.last_job.error : null
  return (
    <div className="flex flex-col gap-4">
      <ScreenTitle title={ch.name} subtitle={`@${ch.handle}`} back />
      <Stepper step={maxStep === 5 && step === null ? 5 : view} maxStep={maxStep} onPick={setStep} />
      {failed && <ErrorNote text={t('wiz.jobFailed', { err: errorText(failed) })} />}
      {maxStep === 5 && step === null ? (
        <Done ch={ch} />
      ) : view === 0 ? (
        <EditCard ch={ch} />
      ) : view === 1 ? (
        <Candidates ch={ch} />
      ) : view === 2 ? (
        <Refs ch={ch} />
      ) : view === 3 ? (
        ch.status === 'training' ? <Training /> : <Refs ch={ch} />
      ) : (
        <Testing ch={ch} />
      )}
    </div>
  )
}

export function WizardScreen({ id }: { id?: number }) {
  return id ? <ExistingWizard id={id} /> : <NewCard />
}

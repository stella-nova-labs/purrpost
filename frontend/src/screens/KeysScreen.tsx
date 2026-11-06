import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'

import { Button, Card, ErrorNote, Field, Input, ScreenTitle } from '../components/ui'
import { errorText, t } from '../i18n'
import { errCode, getKeys, putKeys } from '../lib/api'

function KeyField({ label, current, name }: { label: string; current: string | null | undefined; name: 'fal' | 'anthropic' }) {
  const qc = useQueryClient()
  const [v, setV] = useState('')
  const m = useMutation({
    mutationFn: (value: string) => putKeys({ [name]: value }),
    onSuccess: (data) => {
      qc.setQueryData(['keys'], data)
      void qc.invalidateQueries({ queryKey: ['me'] })
      setV('')
    },
  })
  return (
    <Card className="flex flex-col gap-3 p-4">
      <Field label={label} hint={t('keys.current', { v: current ?? t('keys.none') })}>
        <Input type="password" autoComplete="off" value={v} onChange={(e) => setV(e.target.value)} placeholder={t('keys.placeholder')} />
      </Field>
      {m.isError && <ErrorNote text={errorText(errCode(m.error))} />}
      <div className="flex gap-2">
        <Button className="flex-1" disabled={!v.trim() || m.isPending} onClick={() => m.mutate(v.trim())}>
          {t('common.save')}
        </Button>
        {current && (
          <Button kind="ghost" onClick={() => m.mutate('')}>
            {t('keys.remove')}
          </Button>
        )}
      </div>
    </Card>
  )
}

export function KeysScreen() {
  const keys = useQuery({ queryKey: ['keys'], queryFn: getKeys })
  return (
    <div className="flex flex-col gap-4">
      <ScreenTitle title={t('keys.title')} back />
      <p className="m-0 text-[14px] text-muted">{t('keys.text')}</p>
      <KeyField name="fal" label={t('keys.fal')} current={keys.data?.fal} />
      <KeyField name="anthropic" label={t('keys.anthropic')} current={keys.data?.anthropic} />
    </div>
  )
}

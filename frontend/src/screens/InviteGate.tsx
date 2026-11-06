import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'

import { Icon } from '../components/icons'
import { Button, ErrorNote, Input } from '../components/ui'
import { errorText, t } from '../i18n'
import { errCode, redeemInvite } from '../lib/api'

export function InviteGate() {
  const qc = useQueryClient()
  const [code, setCode] = useState('')
  const m = useMutation({ mutationFn: () => redeemInvite(code), onSuccess: () => qc.invalidateQueries({ queryKey: ['me'] }) })
  return (
    <div className="flex h-full flex-col items-center justify-center gap-5 px-6">
      <div className="flex h-20 w-20 items-center justify-center rounded-3xl bg-accent text-ground">
        <Icon name="cat" size={44} />
      </div>
      <div className="flex flex-col items-center gap-2 text-center">
        <h1 className="m-0 font-display text-[22px] font-bold">{t('invite.title')}</h1>
        <p className="m-0 text-[14px] text-muted">{t('invite.text')}</p>
      </div>
      <form
        className="flex w-full max-w-sm flex-col gap-3"
        onSubmit={(e) => {
          e.preventDefault()
          if (code.trim()) m.mutate()
        }}
      >
        <Input
          value={code}
          onChange={(e) => setCode(e.target.value.toUpperCase())}
          placeholder={t('invite.placeholder')}
          className="text-center font-display tracking-[0.2em]"
          autoCapitalize="characters"
        />
        {m.isError && <ErrorNote text={errorText(errCode(m.error))} />}
        <Button type="submit" disabled={!code.trim() || m.isPending}>
          {t('invite.submit')}
        </Button>
      </form>
    </div>
  )
}

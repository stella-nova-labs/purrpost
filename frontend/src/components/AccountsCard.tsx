import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'

import { errorText, t } from '../i18n'
import { type Account, connectTelegram, disconnectAccount, errCode, getMe, listAccounts, oauthStart, type Platform } from '../lib/api'
import { openExternal } from '../lib/telegram'
import { Icon, type IconName } from './icons'
import { Badge, Button, Card, ErrorNote, Input } from './ui'

const ICON: Record<Platform, IconName> = { instagram: 'instagram', threads: 'threads', telegram: 'telegram' }

function Row({ platform, acc, children }: { platform: Platform; acc?: Account; children?: React.ReactNode }) {
  const qc = useQueryClient()
  const off = useMutation({ mutationFn: () => disconnectAccount(acc!.id), onSuccess: () => qc.invalidateQueries({ queryKey: ['accounts'] }) })
  return (
    <div className="flex flex-col gap-2 px-4 py-3">
      <div className="flex items-center gap-3">
        <Icon name={ICON[platform]} />
        <div className="flex min-w-0 flex-1 flex-col">
          <span className="text-[15px] font-bold">{t(`acc.${platform}`)}</span>
          {acc && (
            <span className="truncate text-[12px] text-muted">
              {acc.platform === 'telegram' ? acc.title || acc.username : `@${acc.username}`}
              {acc.token_expires_ms && acc.status === 'ok'
                ? ` · ${t('acc.until', { date: new Date(acc.token_expires_ms).toLocaleDateString('ru-RU') })}`
                : ''}
            </span>
          )}
        </div>
        {acc && acc.status !== 'ok' && <Badge tone="bad">{t(acc.status === 'expired' ? 'acc.expired' : 'acc.error')}</Badge>}
        {acc && acc.status === 'ok' && <Badge tone="ok">ok</Badge>}
        {acc && (
          <button type="button" aria-label={t('acc.disconnect')} className="press p-1 text-muted" onClick={() => off.mutate()}>
            <Icon name="trash" size={18} />
          </button>
        )}
      </div>
      {children}
    </div>
  )
}

function OAuthRow({ platform, cid, acc }: { platform: 'instagram' | 'threads'; cid: number; acc?: Account }) {
  const qc = useQueryClient()
  const me = useQuery({ queryKey: ['me'], queryFn: getMe })
  const available = me.data?.platforms[platform] ?? true
  const [opened, setOpened] = useState(false)
  const start = useMutation({
    mutationFn: () => oauthStart(platform, cid),
    onSuccess: ({ url }) => {
      openExternal(url)
      setOpened(true)
      // the account appears after the browser flow; poll for a while
      for (const ms of [3000, 8000, 15000, 30000]) setTimeout(() => void qc.invalidateQueries({ queryKey: ['accounts', cid] }), ms)
    },
  })
  const need = !acc || acc.status !== 'ok'
  if (!available && !acc)
    return (
      <Row platform={platform}>
        <p className="m-0 text-[12px] text-muted">{t('acc.manual')}</p>
      </Row>
    )
  return (
    <Row platform={platform} acc={acc}>
      {need && (
        <>
          <Button small kind={acc ? 'primary' : 'secondary'} icon="link" disabled={start.isPending} onClick={() => start.mutate()}>
            {acc ? t('acc.reconnect') : t('acc.connect')}
          </Button>
          {platform === 'instagram' && <p className="m-0 text-[12px] text-muted">{t('acc.igHint')}</p>}
          {opened && <p className="m-0 text-[12px] text-ok">{t('acc.openedBrowser')}</p>}
          {start.isError && <ErrorNote text={errorText(errCode(start.error))} />}
        </>
      )}
    </Row>
  )
}

function TelegramRow({ cid, acc }: { cid: number; acc?: Account }) {
  const qc = useQueryClient()
  const [channel, setChannel] = useState('')
  const m = useMutation({
    mutationFn: () => connectTelegram(cid, channel),
    onSuccess: () => {
      setChannel('')
      void qc.invalidateQueries({ queryKey: ['accounts', cid] })
    },
  })
  return (
    <Row platform="telegram" acc={acc}>
      {(!acc || acc.status !== 'ok') && (
        <>
          <div className="flex gap-2">
            <Input value={channel} onChange={(e) => setChannel(e.target.value)} placeholder={t('acc.tgPh')} />
            <Button small kind="secondary" disabled={channel.trim().length < 2 || m.isPending} onClick={() => m.mutate()}>
              {t('acc.connect')}
            </Button>
          </div>
          <p className="m-0 text-[12px] text-muted">{t('acc.tgHint')}</p>
          {m.isError && <ErrorNote text={errorText(errCode(m.error))} />}
        </>
      )}
    </Row>
  )
}

export function AccountsCard({ cid }: { cid: number }) {
  const q = useQuery({ queryKey: ['accounts', cid], queryFn: () => listAccounts(cid) })
  const by = (p: Platform) => q.data?.find((a) => a.platform === p)
  return (
    <>
      {q.data?.length === 0 && <div className="text-[13px] text-warn">{t('acc.none')}</div>}
      <Card className="flex flex-col divide-y divide-line">
        <OAuthRow platform="instagram" cid={cid} acc={by('instagram')} />
        <TelegramRow cid={cid} acc={by('telegram')} />
        <OAuthRow platform="threads" cid={cid} acc={by('threads')} />
      </Card>
    </>
  )
}

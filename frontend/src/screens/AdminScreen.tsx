import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'

import { Badge, Button, Card, Field, Input, ScreenTitle, Section, Toggle } from '../components/ui'
import { t } from '../i18n'
import { adminAutopilot, adminDisableInvite, adminInvites, adminNewInvite, adminOverview, adminPatchUser, adminUsers } from '../lib/api'

export function AdminScreen() {
  const qc = useQueryClient()
  const invites = useQuery({ queryKey: ['admin', 'invites'], queryFn: adminInvites })
  const users = useQuery({ queryKey: ['admin', 'users'], queryFn: adminUsers })
  const overview = useQuery({ queryKey: ['admin', 'overview'], queryFn: adminOverview })
  const auto = useMutation({ mutationFn: ({ id, on }: { id: number; on: boolean }) => adminAutopilot(id, on), onSuccess: () => qc.invalidateQueries({ queryKey: ['admin'] }) })
  const charsOf = (uid: number) => overview.data?.users.find((u) => u.id === uid)?.characters ?? 0
  const [maxUses, setMaxUses] = useState('1')
  const [note, setNote] = useState('')
  const refresh = () => qc.invalidateQueries({ queryKey: ['admin'] })
  const create = useMutation({ mutationFn: () => adminNewInvite(Number(maxUses) || 1, note), onSuccess: () => { setNote(''); void refresh() } })
  const disable = useMutation({ mutationFn: adminDisableInvite, onSuccess: refresh })
  const budget = useMutation({
    mutationFn: ({ id, v }: { id: number; v: number }) => adminPatchUser(id, { budget_usd: v }),
    onSuccess: refresh,
  })

  return (
    <div className="flex flex-col gap-5">
      <ScreenTitle title={t('admin.title')} back />
      <Section title={t('admin.invites')}>
        <Card className="flex flex-col gap-3 p-4">
          <div className="grid grid-cols-[1fr_2fr] gap-2">
            <Field label={t('admin.maxUses')}>
              <Input inputMode="numeric" value={maxUses} onChange={(e) => setMaxUses(e.target.value.replace(/\D/g, ''))} />
            </Field>
            <Field label={t('admin.note')}>
              <Input value={note} onChange={(e) => setNote(e.target.value)} />
            </Field>
          </div>
          <Button icon="plus" onClick={() => create.mutate()} disabled={create.isPending}>
            {t('admin.newInvite')}
          </Button>
        </Card>
        {invites.data?.map((i) => (
          <Card key={i.code} className="flex items-center gap-3 p-3.5">
            <div className="flex min-w-0 flex-1 flex-col gap-0.5">
              <div className="flex items-center gap-2">
                <span className="font-display text-[15px] font-bold tracking-wider">{i.code}</span>
                {!i.active && <Badge tone="bad">{t('admin.disabled')}</Badge>}
              </div>
              <span className="text-[12px] text-muted">
                {t('admin.uses', { uses: i.uses, max: i.max_uses })}
                {i.note ? ` · ${i.note}` : ''}
              </span>
            </div>
            {i.link && (
              <Button small kind="secondary" icon="link" onClick={() => void navigator.clipboard?.writeText(i.link!)}>
                {t('common.copy')}
              </Button>
            )}
            {i.active && (
              <Button small kind="ghost" onClick={() => disable.mutate(i.code)}>
                {t('admin.disable')}
              </Button>
            )}
          </Card>
        ))}
      </Section>
      <Section title={t('admin.users')}>
        {users.data?.map((u) => (
          <Card key={u.id} className="flex items-center gap-3 p-3.5">
            <div className="flex min-w-0 flex-1 flex-col gap-0.5">
              <span className="truncate text-[15px] font-bold">{u.username ? `@${u.username}` : u.first_name || u.id}</span>
              <span className="text-[12px] text-muted">
                {u.is_active ? t('admin.active') : t('admin.inactive')} · ${u.spent_usd.toFixed(2)} · {t('admin.charsOf', { n: charsOf(u.id) })}
                {u.own_keys ? ` · ${t('admin.ownKeys')}` : ''}
              </span>
            </div>
            <label className="flex items-center gap-1.5 text-[12px] text-muted">
              $
              <Input
                className="w-20 py-1.5 text-right"
                inputMode="decimal"
                defaultValue={u.budget_usd}
                onBlur={(e) => {
                  const v = Number(e.target.value)
                  if (!Number.isNaN(v) && v !== u.budget_usd) budget.mutate({ id: u.id, v })
                }}
              />
            </label>
          </Card>
        ))}
      </Section>
      {overview.data && (
        <Section title={t('admin.characters')} right={<span className="text-[12px] text-muted">{t('admin.totalSpent', { v: overview.data.total_spent_usd.toFixed(2) })}</span>}>
          {overview.data.characters.map((c) => (
            <Card key={c.id} className="flex flex-col gap-1 p-3.5">
              <Toggle
                on={c.autopilot}
                onChange={(on) => auto.mutate({ id: c.id, on })}
                label={`${c.name} · @${c.handle}`}
                hint={`${overview.data.users.find((u) => u.id === c.user_id)?.name ?? c.user_id} · ${t(`status.${c.status}`)} · ${t('admin.posts', { n: c.posts })} · ${c.approved_streak}/10`}
              />
            </Card>
          ))}
        </Section>
      )}
    </div>
  )
}

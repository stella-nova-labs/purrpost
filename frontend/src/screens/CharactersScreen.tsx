import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { Icon } from '../components/icons'
import { Badge, Button, Card, Empty, ErrorNote, ScreenTitle, Section, Spinner } from '../components/ui'
import { errorText, t } from '../i18n'
import { type CharacterBrief, errCode, fromTemplate, getTemplates, listCharacters } from '../lib/api'
import { useNav } from '../store/nav'

export function StatusBadge({ c }: { c: CharacterBrief }) {
  if (c.status === 'ready' && c.autopilot) return <Badge tone="ok">{t('status.autopilot')}</Badge>
  return <Badge tone={c.status === 'ready' ? 'accent' : 'neutral'}>{t(`status.${c.status}`)}</Badge>
}

export function Avatar({ src, size = 48 }: { src: string | null; size?: number }) {
  return src ? (
    <img src={src} alt="" className="shrink-0 rounded-full object-cover" style={{ width: size, height: size }} />
  ) : (
    <span className="flex shrink-0 items-center justify-center rounded-full bg-surface-2 text-muted" style={{ width: size, height: size }}>
      <Icon name="cat" size={size * 0.5} />
    </span>
  )
}

export function CharactersScreen() {
  const push = useNav((s) => s.push)
  const qc = useQueryClient()
  const list = useQuery({ queryKey: ['characters'], queryFn: listCharacters })
  const templates = useQuery({ queryKey: ['templates'], queryFn: getTemplates })
  const launch = useMutation({
    mutationFn: fromTemplate,
    onSuccess: (c) => {
      qc.setQueryData(['character', c.id], c)
      void qc.invalidateQueries({ queryKey: ['characters'] })
      push({ name: 'wizard', id: c.id })
    },
  })
  const open = (c: CharacterBrief) => push(c.status === 'ready' ? { name: 'character', id: c.id } : { name: 'wizard', id: c.id })
  return (
    <div className="flex flex-col gap-5">
      <ScreenTitle
        title={t('chars.title')}
        right={
          <Button small icon="plus" onClick={() => push({ name: 'wizard' })}>
            {t('chars.new')}
          </Button>
        }
      />
      {list.isLoading && <Spinner />}
      {list.data?.length === 0 && <Empty title={t('chars.empty')} text={t('chars.emptyText')} />}
      <div className="flex flex-col gap-2.5">
        {list.data?.map((c) => (
          <Card key={c.id} onClick={() => open(c)} className="flex items-center gap-3 p-3">
            <Avatar src={c.avatar} />
            <div className="flex min-w-0 flex-1 flex-col gap-1">
              <span className="truncate font-display text-[15px] font-bold">{c.name}</span>
              <span className="truncate text-[12px] text-muted">@{c.handle}</span>
            </div>
            <StatusBadge c={c} />
            <Icon name="next" size={18} className="text-muted" />
          </Card>
        ))}
      </div>
      <Section title={t('chars.templates')}>
        {launch.isError && <ErrorNote text={errorText(errCode(launch.error))} />}
        {templates.data?.map((tpl) => (
          <Card key={tpl.slug} className="flex flex-col gap-2 p-4">
            <div className="flex items-center gap-2">
              <span className="flex-1 font-display text-[15px] font-bold">{tpl.name}</span>
              <span className="text-[12px] text-muted">@{tpl.handle}</span>
            </div>
            <p className="m-0 text-[13px] text-muted">{tpl.personality}</p>
            <Button small kind="secondary" icon="sparkle" disabled={launch.isPending} onClick={() => launch.mutate(tpl.slug)}>
              {t('chars.launch')}
            </Button>
          </Card>
        ))}
      </Section>
    </div>
  )
}

import { useQuery } from '@tanstack/react-query'

import { Icon } from '../components/icons'
import { Card, ScreenTitle } from '../components/ui'
import { t } from '../i18n'
import { getMe } from '../lib/api'
import { useNav } from '../store/nav'

export function ProfileScreen() {
  const me = useQuery({ queryKey: ['me'], queryFn: getMe })
  const push = useNav((s) => s.push)
  const u = me.data?.user
  return (
    <div className="flex flex-col gap-4">
      <ScreenTitle title={t('profile.title')} subtitle={u?.username ? `@${u.username}` : u?.first_name} />
      {me.data?.fake_providers && <Card className="p-3.5 text-[13px] text-warn">{t('profile.fake')}</Card>}
      {u?.is_admin && (
        <Card onClick={() => push({ name: 'admin' })} className="flex items-center gap-3 p-4">
          <Icon name="key" />
          <span className="flex-1 font-bold">{t('profile.admin')}</span>
          <Icon name="next" size={18} />
        </Card>
      )}
    </div>
  )
}

import { useQuery } from '@tanstack/react-query'
import { useEffect, type ReactNode } from 'react'

import { Icon } from './components/icons'
import { TabBar } from './components/TabBar'
import { Spinner } from './components/ui'
import { t } from './i18n'
import { getMe } from './lib/api'
import { initTelegram } from './lib/telegram'
import { AdminScreen } from './screens/AdminScreen'
import { CharacterScreen } from './screens/CharacterScreen'
import { CharactersScreen } from './screens/CharactersScreen'
import { InviteGate } from './screens/InviteGate'
import { KeysScreen } from './screens/KeysScreen'
import { Placeholder } from './screens/Placeholder'
import { ProfileScreen } from './screens/ProfileScreen'
import { WizardScreen } from './screens/WizardScreen'
import { useNav, type Route, type Tab } from './store/nav'

const TAB_SCREENS: Record<Tab, () => ReactNode> = {
  characters: () => <CharactersScreen />,
  drafts: () => <Placeholder title="tab.drafts" />,
  calendar: () => <Placeholder title="tab.calendar" />,
  dashboard: () => <Placeholder title="tab.dashboard" />,
  profile: () => <ProfileScreen />,
}

function routeScreen(r: Route): ReactNode {
  switch (r.name) {
    case 'admin':
      return <AdminScreen />
    case 'keys':
      return <KeysScreen />
    case 'character':
      return <CharacterScreen key={r.id} id={r.id} />
    case 'wizard':
      return <WizardScreen key={r.id ?? 'new'} id={r.id} />
    default:
      return <Placeholder title="common.soon" />
  }
}

function Splash({ error }: { error?: boolean }) {
  return (
    <div className="flex h-full flex-col items-center justify-center gap-4 px-8 text-center">
      <div className="flex h-20 w-20 items-center justify-center rounded-3xl bg-accent text-ground">
        <Icon name="cat" size={44} />
      </div>
      <div className="font-display text-[22px] font-bold">{t('app.name')}</div>
      {error ? <div className="text-[14px] text-muted">{t('app.offline')}</div> : <Spinner />}
    </div>
  )
}

export default function App() {
  const tab = useNav((s) => s.tab)
  const stack = useNav((s) => s.stack)
  const me = useQuery({ queryKey: ['me'], queryFn: getMe })

  useEffect(() => initTelegram(), [])

  if (me.isError) return <Splash error />
  if (!me.data) return <Splash />
  if (!me.data.user.is_active) return <InviteGate />

  const top = stack[stack.length - 1]
  return (
    <div className="flex h-full flex-col">
      <main className="no-scrollbar flex-1 overflow-y-auto px-4 pt-4 pb-6">{top ? routeScreen(top) : TAB_SCREENS[tab]()}</main>
      <TabBar />
    </div>
  )
}

import { t } from '../i18n'
import { useNav, type Tab } from '../store/nav'
import { Icon, type IconName } from './icons'

const TABS: [Tab, IconName][] = [
  ['characters', 'cat'],
  ['drafts', 'drafts'],
  ['calendar', 'calendar'],
  ['dashboard', 'chart'],
  ['profile', 'user'],
]

export function TabBar({ badges = {} }: { badges?: Partial<Record<Tab, number>> }) {
  const tab = useNav((s) => s.tab)
  const setTab = useNav((s) => s.setTab)
  return (
    <nav className="grid grid-cols-5 gap-1 border-t border-line bg-bar px-2.5 pt-2 pb-[max(14px,env(safe-area-inset-bottom))]">
      {TABS.map(([id, icon]) => {
        const on = tab === id
        const n = badges[id]
        return (
          <button
            key={id}
            type="button"
            onClick={() => setTab(id)}
            className={`relative flex flex-col items-center gap-1 rounded-xl py-1.5 ${on ? 'bg-surface-2 text-accent' : 'text-muted'}`}
          >
            <Icon name={icon} />
            <span className="text-[11px] font-bold">{t(`tab.${id}`)}</span>
            {!!n && (
              <span className="absolute top-0.5 right-[22%] min-w-[18px] rounded-full bg-pink px-1 text-[10px] font-extrabold text-ground">{n}</span>
            )}
          </button>
        )
      })}
    </nav>
  )
}

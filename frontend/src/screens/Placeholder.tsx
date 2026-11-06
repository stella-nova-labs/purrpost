import { Empty, ScreenTitle } from '../components/ui'
import { t, type Key } from '../i18n'

export function Placeholder({ title }: { title: Key }) {
  return (
    <div className="flex flex-col gap-4">
      <ScreenTitle title={t(title)} />
      <Empty title={t('common.soon')} />
    </div>
  )
}

import { t } from '../i18n'
import type { DraftStatus } from '../lib/api'
import { Badge } from './ui'

const TONE: Record<DraftStatus, 'neutral' | 'accent' | 'ok' | 'warn' | 'bad'> = {
  generating: 'neutral',
  pending_review: 'accent',
  needs_review: 'warn',
  scheduled: 'ok',
  publishing: 'ok',
  published: 'ok',
  partially_published: 'warn',
  failed: 'bad',
  skipped: 'neutral',
}

export function DraftBadge({ status }: { status: DraftStatus }) {
  return <Badge tone={TONE[status]}>{t(`dstatus.${status}`)}</Badge>
}

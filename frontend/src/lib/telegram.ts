// Wrapper over window.Telegram.WebApp: in a regular browser (local development) everything is a safe no-op.

type Haptic = {
  impactOccurred: (style: 'light' | 'medium' | 'heavy' | 'rigid' | 'soft') => void
  notificationOccurred: (type: 'error' | 'success' | 'warning') => void
}

type WebApp = {
  initData: string
  initDataUnsafe?: { start_param?: string }
  ready: () => void
  expand: () => void
  disableVerticalSwipes?: () => void
  setHeaderColor?: (color: string) => void
  setBackgroundColor?: (color: string) => void
  openTelegramLink: (url: string) => void
  openLink: (url: string) => void
  showConfirm?: (message: string, cb: (ok: boolean) => void) => void
  HapticFeedback?: Haptic
}

declare global {
  interface Window {
    Telegram?: { WebApp?: WebApp }
  }
}

export const tg: WebApp | undefined = window.Telegram?.WebApp?.initData ? window.Telegram.WebApp : undefined

export function initTelegram() {
  if (!tg) return
  tg.ready()
  tg.expand()
  tg.disableVerticalSwipes?.()
  tg.setHeaderColor?.('#120F16')
  tg.setBackgroundColor?.('#120F16')
}

/** External link in the system browser (Instagram sign-in doesn't work inside the Telegram WebView). */
export function openExternal(url: string) {
  if (tg) tg.openLink(url)
  else window.open(url, '_blank')
}

export function haptic(style: 'light' | 'medium' | 'heavy' = 'light') {
  tg?.HapticFeedback?.impactOccurred(style)
}

export function confirmAction(message: string): Promise<boolean> {
  return new Promise((resolve) => {
    if (tg?.showConfirm) tg.showConfirm(message, resolve)
    else resolve(window.confirm(message))
  })
}

/** Authorization header. Outside Telegram it's a dev user (the backend accepts it only with DEV_AUTH=1):
 * `?dev=<id>` picks the user, `&start=inv_CODE` imitates an invite link. */
export function authHeader(): string {
  if (tg) return `tma ${tg.initData}`
  const q = new URLSearchParams(location.search)
  const id = q.get('dev') ?? '1'
  const start = q.get('start')
  return `tma dev:${id}${start ? `:${start}` : ''}`
}

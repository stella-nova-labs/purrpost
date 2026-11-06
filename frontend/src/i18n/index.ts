import { ru } from './ru'

export type Key = keyof typeof ru
type Dict = Record<Key, string>

// English goes here later: `const en: Partial<Dict> = {...}` and pick by Telegram language.
const dicts: Record<string, Partial<Dict>> = { ru }
const lang = 'ru'

/** `t('drafts.count', { n: 3 })`: `{n}` placeholders are replaced with values. */
export function t(key: Key, vars?: Record<string, string | number>): string {
  let s = dicts[lang][key] ?? ru[key] ?? key
  if (vars) for (const [k, v] of Object.entries(vars)) s = s.replaceAll(`{${k}}`, String(v))
  return s
}

/** Error code from the API (`detail`) -> human text. Unknown codes fall back to a generic message. */
export function errorText(code: string): string {
  const key = `err.${code}` as Key
  return key in ru ? t(key) : t('err.generic')
}

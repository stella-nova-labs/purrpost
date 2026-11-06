import { authHeader } from './telegram'

export class ApiError extends Error {
  status: number
  detail: string
  constructor(status: number, detail: string) {
    super(detail)
    this.status = status
    this.detail = detail
  }
}

export async function api<T>(path: string, init: { method?: string; body?: unknown } = {}): Promise<T> {
  let res: Response
  try {
    res = await fetch(path, {
      method: init.method ?? (init.body === undefined ? 'GET' : 'POST'),
      headers: { Authorization: authHeader(), ...(init.body === undefined ? {} : { 'Content-Type': 'application/json' }) },
      body: init.body === undefined ? undefined : JSON.stringify(init.body),
    })
  } catch {
    throw new ApiError(0, 'network')
  }
  if (!res.ok) {
    let detail = `http_${res.status}`
    try {
      const j = await res.json()
      if (typeof j.detail === 'string') detail = j.detail
      else if (j.detail?.code) detail = j.detail.code
    } catch {
      /* not json */
    }
    throw new ApiError(res.status, detail)
  }
  return (await res.json()) as T
}

export const errCode = (e: unknown) => (e instanceof ApiError ? e.detail : 'generic')

// ---- types ----
export type User = {
  id: number
  first_name: string
  username: string | null
  is_active: boolean
  is_owner: boolean
  is_admin: boolean
}
export type Budget = { limit: number; spent: number; spent_own_keys: number; remaining: number; exhausted: boolean; month: string }
export type Me = { user: User; fake_providers: boolean; budget?: Budget; own_keys?: { fal: boolean; anthropic: boolean } }
export type Keys = { fal: string | null; anthropic: string | null }

export type Invite = { code: string; max_uses: number; uses: number; note: string; active: boolean; created_ms: number; link: string | null }
export type AdminUserRow = {
  id: number
  first_name: string
  username: string | null
  is_active: boolean
  budget_usd: number
  spent_usd: number
  spent_own_usd: number
  own_keys: boolean
  invite_code: string | null
  created_ms: number
}

// ---- calls ----
export const getMe = () => api<Me>('/api/me')
export const redeemInvite = (code: string) => api<{ user: User }>('/api/invite/redeem', { body: { code } })
export const adminInvites = () => api<Invite[]>('/api/admin/invites')
export const adminNewInvite = (max_uses: number, note: string) => api<Invite>('/api/admin/invites', { body: { max_uses, note } })
export const adminDisableInvite = (code: string) => api<{ ok: boolean }>(`/api/admin/invites/${code}`, { method: 'DELETE' })
export const adminUsers = () => api<AdminUserRow[]>('/api/admin/users')
export const adminPatchUser = (id: number, body: { budget_usd?: number; is_active?: boolean }) =>
  api<{ ok: boolean }>(`/api/admin/users/${id}`, { method: 'PATCH', body })
export const getKeys = () => api<Keys>('/api/me/keys')
export const putKeys = (body: { fal?: string; anthropic?: string }) => api<Keys>('/api/me/keys', { method: 'PUT', body })

// ---- characters ----
export type Rubric = { weekday: number | null; title: string; description: string }
export type Appearance = { breed: string; color: string; marks: string; signature: string }
export type CardData = {
  name: string
  handle: string
  personality: string
  pain: string
  humor: string
  language: string
  appearance: Appearance
  rubrics: Rubric[]
  stop_topics: string[]
  notes: string
}
export type CharStatus = 'appearance' | 'refsheet' | 'training' | 'testing' | 'ready'
export type CharImage = { id: number; kind: string; url: string; batch: number }
export type Schedule = { times: string[]; days: number[]; tz: string; lead_hours: number }
export type CharacterBrief = {
  id: number
  name: string
  handle: string
  status: CharStatus
  template: string | null
  autopilot: boolean
  approved_streak: number
  avatar: string | null
}
export type Character = CharacterBrief & {
  card: CardData
  appearance_text: string
  chosen_image_id: number | null
  lora_trigger: string
  has_lora: boolean
  training_error: string | null
  candidates: CharImage[]
  refs: CharImage[]
  tests: CharImage[]
  busy: string[]
  min_refs: number
  last_job: { kind: string; status: string; error: string | null } | null
  schedule: Schedule
  slides_max: number
  ai_disclosure: boolean
  disclosure_text: string
  trend: string
  lore: { date: string; rubric: string; summary: string }[]
}
export type Template = { slug: string; name: string; handle: string; personality: string; notes: string }

export const getTemplates = () => api<Template[]>('/api/templates')
export const suggestCard = (idea: string) => api<CardData>('/api/characters/suggest', { body: { idea } })
export const listCharacters = () => api<CharacterBrief[]>('/api/characters')
export const getCharacter = (id: number) => api<Character>(`/api/characters/${id}`)
export const createCharacter = (card: CardData) => api<Character>('/api/characters', { body: card })
export const fromTemplate = (slug: string) => api<Character>(`/api/characters/from-template/${slug}`, { method: 'POST' })
export const putCard = (id: number, card: CardData) => api<Character>(`/api/characters/${id}/card`, { method: 'PUT', body: card })
export const requestCandidates = (id: number, count: number, extra: string) =>
  api<Character>(`/api/characters/${id}/candidates`, { body: { count, extra } })
export const chooseCandidate = (id: number, image_id: number) => api<Character>(`/api/characters/${id}/choose`, { body: { image_id } })
export const requestRefsheet = (id: number, count = 16) => api<Character>(`/api/characters/${id}/refsheet`, { body: { count } })
export const deleteImage = (id: number, imageId: number) => api<Character>(`/api/characters/${id}/images/${imageId}`, { method: 'DELETE' })
export const startTraining = (id: number) => api<Character>(`/api/characters/${id}/train`, { method: 'POST' })
export const confirmLora = (id: number, ok: boolean) => api<Character>(`/api/characters/${id}/confirm`, { body: { ok } })
export const archiveCharacter = (id: number) => api<{ ok: boolean }>(`/api/characters/${id}`, { method: 'DELETE' })

// ---- drafts ----
export type DraftStatus =
  | 'generating'
  | 'pending_review'
  | 'needs_review'
  | 'scheduled'
  | 'publishing'
  | 'published'
  | 'partially_published'
  | 'failed'
  | 'skipped'
export type DraftSlide = { index: number; scene: string; url: string; ok: boolean; issues: string[] }
export type Draft = {
  id: number
  character: { id: number; name: string; handle: string }
  slot_ms: number
  rubric: string
  trend: string
  idea: string
  caption: string
  hashtags: string[]
  alt_text: string
  status: DraftStatus
  qa_ok: boolean
  error: string | null
  slides: DraftSlide[]
  final_caption: string
  busy: string[]
  approved_ms: number | null
  published_ms: number | null
  created_ms: number
  publications: { platform: Platform; status: string; permalink: string | null; attempts: number; error: string | null }[]
}
export type SettingsPatch = {
  schedule?: Schedule
  slides_max?: number
  ai_disclosure?: boolean
  disclosure_text?: string
  trend?: string
}

export const listDrafts = (params: { status?: string; character_id?: number; from_ms?: number; to_ms?: number } = {}) => {
  const q = new URLSearchParams(Object.entries(params).filter(([, v]) => v !== undefined).map(([k, v]) => [k, String(v)]))
  return api<Draft[]>(`/api/drafts?${q}`)
}
export const getDraft = (id: number) => api<Draft>(`/api/drafts/${id}`)
export const generateNow = (id: number, trend?: string) => api<Draft>(`/api/characters/${id}/generate`, { body: { trend: trend || null } })
export const patchSettings = (id: number, body: SettingsPatch) => api<Character>(`/api/characters/${id}/settings`, { method: 'PATCH', body })
export const approveDraft = (id: number) => api<Draft>(`/api/drafts/${id}/approve`, { method: 'POST' })
export const unscheduleDraft = (id: number) => api<Draft>(`/api/drafts/${id}/unschedule`, { method: 'POST' })
export const skipDraft = (id: number) => api<Draft>(`/api/drafts/${id}/skip`, { method: 'POST' })
export const regenerateDraft = (id: number, what: 'all' | 'images', slides?: number[]) =>
  api<Draft>(`/api/drafts/${id}/regenerate`, { body: { what, slides } })
export const editDraft = (id: number, body: { caption?: string; hashtags?: string[]; order?: number[] }) =>
  api<Draft>(`/api/drafts/${id}`, { method: 'PATCH', body })

export type CalendarItem = {
  id: number
  character: { id: number; name: string; handle: string }
  slot_ms: number
  status: DraftStatus
  rubric: string
  idea: string
  thumb: string | null
}
export type CalendarData = { drafts: CalendarItem[]; planned: { character: { id: number; name: string; handle: string }; slot_ms: number }[] }
export const getCalendar = (from_ms: number, to_ms: number) => api<CalendarData>(`/api/calendar?from_ms=${from_ms}&to_ms=${to_ms}`)

// ---- accounts ----
export type Platform = 'instagram' | 'threads' | 'telegram'
export type Account = {
  id: number
  platform: Platform
  username: string
  status: 'ok' | 'expired' | 'error'
  last_error: string | null
  token_expires_ms: number | null
  title: string | null
}
export const listAccounts = (cid: number) => api<Account[]>(`/api/characters/${cid}/accounts`)
export const oauthStart = (platform: 'instagram' | 'threads', cid: number) =>
  api<{ url: string }>(`/api/oauth/${platform}/start?character_id=${cid}`)
export const connectTelegram = (cid: number, channel: string) => api<Account>(`/api/characters/${cid}/accounts/telegram`, { body: { channel } })
export const disconnectAccount = (id: number) => api<{ ok: boolean }>(`/api/accounts/${id}`, { method: 'DELETE' })

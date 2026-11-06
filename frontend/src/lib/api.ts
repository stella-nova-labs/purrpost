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
export type Me = { user: User; fake_providers: boolean }

export type Invite = { code: string; max_uses: number; uses: number; note: string; active: boolean; created_ms: number; link: string | null }
export type AdminUserRow = {
  id: number
  first_name: string
  username: string | null
  is_active: boolean
  budget_usd: number
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

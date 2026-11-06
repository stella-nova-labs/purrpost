import { create } from 'zustand'

export type Tab = 'characters' | 'drafts' | 'calendar' | 'dashboard' | 'profile'
/** Screens pushed on top of a tab (wizard, character, draft, admin). */
export type Route =
  | { name: 'admin' }
  | { name: 'wizard'; id?: number }
  | { name: 'character'; id: number }
  | { name: 'draft'; id: number }
  | { name: 'keys' }

type Nav = {
  tab: Tab
  stack: Route[]
  setTab: (t: Tab) => void
  push: (r: Route) => void
  pop: () => void
  replace: (r: Route) => void
}

export const useNav = create<Nav>((set) => ({
  tab: 'characters',
  stack: [],
  setTab: (tab) => set({ tab, stack: [] }),
  push: (r) => set((s) => ({ stack: [...s.stack, r] })),
  pop: () => set((s) => ({ stack: s.stack.slice(0, -1) })),
  replace: (r) => set((s) => ({ stack: [...s.stack.slice(0, -1), r] })),
}))

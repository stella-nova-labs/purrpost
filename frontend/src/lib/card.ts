import type { CardData } from './api'

export const EMPTY_CARD: CardData = {
  name: '',
  handle: '',
  personality: '',
  pain: '',
  humor: '',
  language: 'en',
  appearance: { breed: '', color: '', marks: '', signature: '' },
  rubrics: [],
  stop_topics: [],
  notes: '',
}

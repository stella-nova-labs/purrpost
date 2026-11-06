const WD = ['вс', 'пн', 'вт', 'ср', 'чт', 'пт', 'сб']

/** «пт, 7 нояб., 18:00» in the viewer's local time. */
export function slotText(ms: number): string {
  const d = new Date(ms)
  const date = d.toLocaleDateString('ru-RU', { day: 'numeric', month: 'short' })
  const time = d.toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' })
  return `${WD[d.getDay()]}, ${date}, ${time}`
}

export function timeText(ms: number): string {
  return new Date(ms).toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' })
}

export function dayKey(ms: number): string {
  const d = new Date(ms)
  return `${d.getFullYear()}-${d.getMonth()}-${d.getDate()}`
}

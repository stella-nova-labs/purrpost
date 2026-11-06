import { motion } from 'framer-motion'

import type { CharImage } from '../lib/api'
import { Icon } from './icons'

export function ImageGrid({
  images,
  cols = 3,
  selected,
  onPick,
  onDelete,
  aspect = '4/5',
}: {
  images: CharImage[]
  cols?: number
  selected?: number | null
  onPick?: (img: CharImage) => void
  onDelete?: (img: CharImage) => void
  aspect?: string
}) {
  return (
    <div className="grid gap-2" style={{ gridTemplateColumns: `repeat(${cols}, minmax(0, 1fr))` }}>
      {images.map((img, i) => (
        <motion.div
          key={img.id}
          initial={{ opacity: 0, scale: 0.94 }}
          animate={{ opacity: 1, scale: 1 }}
          transition={{ delay: Math.min(i, 12) * 0.03 }}
          className={`relative overflow-hidden rounded-xl border-2 ${selected === img.id ? 'border-accent' : 'border-transparent'}`}
          style={{ aspectRatio: aspect }}
        >
          <button type="button" className="block h-full w-full" onClick={() => onPick?.(img)} disabled={!onPick}>
            <img src={img.url} alt="" className="h-full w-full object-cover" loading="lazy" />
          </button>
          {selected === img.id && (
            <span className="absolute top-1.5 left-1.5 flex h-6 w-6 items-center justify-center rounded-full bg-accent text-ground">
              <Icon name="check" size={16} />
            </span>
          )}
          {onDelete && (
            <button
              type="button"
              aria-label="delete"
              onClick={() => onDelete(img)}
              className="absolute top-1.5 right-1.5 flex h-7 w-7 items-center justify-center rounded-full bg-ground/75 text-ink backdrop-blur"
            >
              <Icon name="skip" size={15} />
            </button>
          )}
        </motion.div>
      ))}
    </div>
  )
}

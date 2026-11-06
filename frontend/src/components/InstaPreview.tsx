import { useRef, useState } from 'react'

import { t } from '../i18n'
import type { DraftSlide } from '../lib/api'
import { Icon } from './icons'

/** A post as it will look in Instagram: 4:5 carousel, handle, caption with "more". */
export function InstaPreview({ handle, avatar, slides, caption }: { handle: string; avatar: string | null; slides: DraftSlide[]; caption: string }) {
  const [i, setI] = useState(0)
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)
  const onScroll = () => {
    const el = ref.current
    if (el) setI(Math.round(el.scrollLeft / el.clientWidth))
  }
  const short = caption.length > 120 && !open
  return (
    <div className="overflow-hidden rounded-2xl border border-line bg-[#000] text-[#F5F5F5]">
      <div className="flex items-center gap-2.5 px-3 py-2.5">
        {avatar ? <img src={avatar} alt="" className="h-8 w-8 rounded-full object-cover" /> : <span className="h-8 w-8 rounded-full bg-surface-2" />}
        <span className="flex-1 text-[14px] font-bold">{handle}</span>
        <Icon name="dots" size={20} />
      </div>
      <div className="relative">
        <div ref={ref} onScroll={onScroll} className="no-scrollbar flex snap-x snap-mandatory overflow-x-auto">
          {slides.map((sl) => (
            <img key={sl.url} src={sl.url} alt={sl.scene} className="aspect-[4/5] w-full shrink-0 snap-center object-cover" />
          ))}
        </div>
        {slides.length > 1 && (
          <span className="absolute top-3 right-3 rounded-full bg-black/60 px-2 py-0.5 text-[12px] font-bold">
            {i + 1}/{slides.length}
          </span>
        )}
      </div>
      <div className="flex items-center gap-4 px-3 pt-2.5">
        <Icon name="heart" />
        <Icon name="comment" />
        <Icon name="send" />
        <span className="flex flex-1 justify-center gap-1">
          {slides.length > 1 &&
            slides.map((_, j) => <span key={j} className={`h-1.5 w-1.5 rounded-full ${j === i ? 'bg-[#3897F0]' : 'bg-white/30'}`} />)}
        </span>
        <Icon name="bookmark" />
      </div>
      <div className="px-3 pt-2 pb-3 text-[14px] leading-snug">
        <div className="mb-1 font-bold">{t('draft.likes', { n: '—' })}</div>
        <span className="font-bold">{handle}</span>{' '}
        <span className="whitespace-pre-line">{short ? caption.slice(0, 120).trimEnd() + '… ' : caption}</span>
        {short && (
          <button type="button" className="text-white/55" onClick={() => setOpen(true)}>
            {t('draft.more')}
          </button>
        )}
      </div>
    </div>
  )
}

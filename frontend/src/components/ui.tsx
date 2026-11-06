import type { ReactNode } from 'react'

import { t } from '../i18n'
import { useNav } from '../store/nav'
import { Icon, type IconName } from './icons'

export function Card({ children, className = '', onClick }: { children: ReactNode; className?: string; onClick?: () => void }) {
  const cls = `rounded-2xl border border-line bg-surface ${className}`
  if (onClick)
    return (
      <button type="button" onClick={onClick} className={`press block w-full text-left ${cls}`}>
        {children}
      </button>
    )
  return <div className={cls}>{children}</div>
}

export function ScreenTitle({ title, subtitle, back, right }: { title: string; subtitle?: string; back?: boolean; right?: ReactNode }) {
  const pop = useNav((s) => s.pop)
  return (
    <div className="flex items-center gap-2.5">
      {back && (
        <button
          type="button"
          aria-label={t('common.back')}
          onClick={pop}
          className="press flex h-10 w-10 shrink-0 items-center justify-center rounded-xl border border-line bg-surface"
        >
          <Icon name="back" size={20} />
        </button>
      )}
      <div className="flex min-w-0 flex-1 flex-col gap-0.5">
        <h1 className="m-0 truncate font-display text-[20px] font-bold">{title}</h1>
        {subtitle && <div className="text-[13px] text-muted">{subtitle}</div>}
      </div>
      {right}
    </div>
  )
}

type BtnKind = 'primary' | 'secondary' | 'ghost' | 'danger' | 'ok'
const BTN: Record<BtnKind, string> = {
  primary: 'bg-accent text-ground',
  secondary: 'border border-line-2 bg-surface-2 text-ink',
  ghost: 'text-muted',
  danger: 'border border-bad/40 bg-bad-deep text-bad',
  ok: 'bg-ok text-ground',
}

export function Button({
  children,
  onClick,
  kind = 'primary',
  disabled,
  icon,
  className = '',
  small,
  type = 'button',
}: {
  children: ReactNode
  onClick?: () => void
  kind?: BtnKind
  disabled?: boolean
  icon?: IconName
  className?: string
  small?: boolean
  type?: 'button' | 'submit'
}) {
  return (
    <button
      type={type}
      onClick={onClick}
      disabled={disabled}
      className={`press inline-flex items-center justify-center gap-2 rounded-xl font-bold disabled:opacity-40 ${
        small ? 'px-3 py-2 text-[13px]' : 'px-4 py-3 text-[15px]'
      } ${BTN[kind]} ${className}`}
    >
      {icon && <Icon name={icon} size={small ? 16 : 18} />}
      {children}
    </button>
  )
}

export function Field({ label, hint, children }: { label: string; hint?: string; children: ReactNode }) {
  return (
    <label className="flex flex-col gap-1.5">
      <span className="text-[13px] font-bold text-muted">{label}</span>
      {children}
      {hint && <span className="text-[12px] text-muted/80">{hint}</span>}
    </label>
  )
}

const INPUT = 'w-full rounded-xl border border-line bg-surface-2 px-3 py-2.5 text-[15px] outline-none focus:border-accent'

export function Input(props: React.InputHTMLAttributes<HTMLInputElement>) {
  return <input {...props} className={`${INPUT} ${props.className ?? ''}`} />
}

export function TextArea(props: React.TextareaHTMLAttributes<HTMLTextAreaElement>) {
  return <textarea rows={3} {...props} className={`${INPUT} resize-none ${props.className ?? ''}`} />
}

export function Segmented<T extends string>({ value, options, onChange }: { value: T; options: [T, string][]; onChange: (v: T) => void }) {
  return (
    <div className="grid gap-1 rounded-[14px] border border-line bg-surface p-1" style={{ gridTemplateColumns: `repeat(${options.length}, minmax(0, 1fr))` }}>
      {options.map(([v, label]) => (
        <button
          key={v}
          type="button"
          onClick={() => onChange(v)}
          className={`rounded-[10px] py-2 text-[13px] font-bold ${v === value ? 'bg-line text-ink' : 'text-muted'}`}
        >
          {label}
        </button>
      ))}
    </div>
  )
}

export function Toggle({ on, onChange, label, hint, disabled }: { on: boolean; onChange: (v: boolean) => void; label: string; hint?: string; disabled?: boolean }) {
  return (
    <button
      type="button"
      disabled={disabled}
      onClick={() => onChange(!on)}
      className="flex w-full items-center gap-3 text-left disabled:opacity-50"
    >
      <div className="flex min-w-0 flex-1 flex-col">
        <span className="text-[15px] font-bold">{label}</span>
        {hint && <span className="text-[12px] text-muted">{hint}</span>}
      </div>
      <span className={`relative h-7 w-12 shrink-0 rounded-full transition-colors ${on ? 'bg-accent' : 'bg-line-2'}`}>
        <span className={`absolute top-1 h-5 w-5 rounded-full bg-ink transition-[left] ${on ? 'left-6' : 'left-1'}`} />
      </span>
    </button>
  )
}

type Tone = 'neutral' | 'accent' | 'ok' | 'warn' | 'bad'
const TONE: Record<Tone, string> = {
  neutral: 'bg-surface-2 text-muted',
  accent: 'bg-accent-deep text-accent',
  ok: 'bg-ok-deep text-ok',
  warn: 'bg-warn-deep text-warn',
  bad: 'bg-bad-deep text-bad',
}

export function Badge({ children, tone = 'neutral' }: { children: ReactNode; tone?: Tone }) {
  return <span className={`inline-flex items-center rounded-full px-2 py-0.5 text-[11px] font-bold ${TONE[tone]}`}>{children}</span>
}

export function Spinner({ size = 20 }: { size?: number }) {
  return (
    <span
      className="inline-block animate-spin rounded-full border-2 border-line-2 border-t-accent"
      style={{ width: size, height: size }}
      aria-label="loading"
    />
  )
}

export function Empty({ icon = 'cat', title, text, action }: { icon?: IconName; title: string; text?: string; action?: ReactNode }) {
  return (
    <div className="flex flex-col items-center gap-2 rounded-2xl border border-dashed border-line px-6 py-10 text-center">
      <span className="text-muted">
        <Icon name={icon} size={34} />
      </span>
      <div className="font-display text-[15px] font-bold">{title}</div>
      {text && <div className="text-[13px] text-muted">{text}</div>}
      {action && <div className="mt-2">{action}</div>}
    </div>
  )
}

export function ErrorNote({ text }: { text: string }) {
  return <div className="rounded-xl border border-bad/30 bg-bad-deep px-3 py-2.5 text-[13px] text-bad">{text}</div>
}

export function Section({ title, children, right }: { title: string; children: ReactNode; right?: ReactNode }) {
  return (
    <section className="flex flex-col gap-2.5">
      <div className="flex items-center justify-between">
        <h2 className="m-0 font-display text-[14px] font-bold uppercase tracking-wide text-muted">{title}</h2>
        {right}
      </div>
      {children}
    </section>
  )
}

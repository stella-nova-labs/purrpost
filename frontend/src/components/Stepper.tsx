import { t } from '../i18n'

const STEPS = ['wiz.step1', 'wiz.step2', 'wiz.step3', 'wiz.step4', 'wiz.step5'] as const

export function Stepper({ step, onPick, maxStep }: { step: number; onPick?: (i: number) => void; maxStep: number }) {
  return (
    <div className="grid grid-cols-5 gap-1.5">
      {STEPS.map((k, i) => {
        const on = i === step
        const done = i < maxStep
        return (
          <button
            key={k}
            type="button"
            disabled={!onPick || i > maxStep}
            onClick={() => onPick?.(i)}
            className="flex flex-col items-center gap-1.5 disabled:cursor-default"
          >
            <span className={`h-1.5 w-full rounded-full ${on ? 'bg-accent' : done ? 'bg-accent/45' : 'bg-line'}`} />
            <span className={`text-[10.5px] font-bold ${on ? 'text-ink' : 'text-muted'}`}>{t(k)}</span>
          </button>
        )
      })}
    </div>
  )
}

import { cn } from '../../utils/cn'

/**
 * Badges are printed labels, not candy: square-ish, uppercase, tracked,
 * tint-on-hairline. The risk vocabulary (moss → ochre → rust → clay) matches
 * RISK_COLORS in data/network-connections.js and the map legend.
 *
 * `uncalibrated` exists because the engine now reports it (a standardized
 * model score is not a risk level until calibration exists — see
 * docs/QUANT_REVIEW_2026-09.md). It renders deliberately quieter, with a
 * dashed rule: absence of calibration should be visible, not dressed up.
 */
const variants = {
  default: 'bg-bne-paper-dim text-bne-muted border border-bne-line',
  primary: 'bg-bne-pine-50 text-bne-pine-700 border border-bne-pine-100',
  success: 'bg-bne-moss-50 text-bne-moss-600 border border-bne-moss/30',
  warning: 'bg-bne-ochre-50 text-bne-ochre-600 border border-bne-ochre/30',
  danger: 'bg-bne-clay-50 text-bne-clay-600 border border-bne-clay/30',
  high: 'bg-bne-rust-50 text-bne-rust-600 border border-bne-rust/30',
  info: 'bg-bne-stone-50 text-bne-stone border border-bne-stone/30',
  neutral: 'bg-bne-stone-50 text-bne-stone border border-bne-stone/30',
  uncalibrated:
    'bg-bne-paper-dim text-bne-faint border border-dashed border-bne-line-strong'
}

const sizes = {
  sm: 'px-1.5 py-[1px] text-[10px]',
  md: 'px-2 py-0.5 text-[10.5px]',
  lg: 'px-2.5 py-1 text-xs'
}

export default function Badge({
  children,
  variant = 'default',
  size = 'md',
  className,
  ...props
}) {
  return (
    <span
      className={cn(
        'inline-flex items-center rounded-[3px] font-semibold uppercase tracking-micro whitespace-nowrap',
        variants[variant] || variants.default,
        sizes[size] || sizes.md,
        className
      )}
      {...props}
    >
      {children}
    </span>
  )
}

/**
 * Map a backend risk level or status string to a badge variant. One place,
 * so every page renders the same vocabulary — including the levels the
 * engine can now emit ("uncalibrated") and unknown values (quiet neutral,
 * never silently "success").
 */
export function riskVariant(level) {
  switch (String(level ?? '').toLowerCase()) {
    case 'low':
      return 'success'
    case 'medium':
    case 'moderate':
      return 'warning'
    case 'elevated':
    case 'high':
      return 'high'
    case 'critical':
    case 'severe':
      return 'danger'
    case 'uncalibrated':
      return 'uncalibrated'
    default:
      return 'neutral'
  }
}

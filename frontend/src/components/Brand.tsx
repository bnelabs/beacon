import { type ReactNode } from 'react'
import { cn } from '../utils/cn'

export interface BeaconMarkProps {
  className?: string
  lampClass?: string
}

/**
 * The BEACON mark: a signal tower with a lit lamp and two broadcast arcs.
 *
 * Drawn on the same 24-unit grid and 1.6 stroke as the navigation icons so
 * the brand sits inside the icon system rather than on top of it. Ink tower,
 * ochre lamp, pine signal — the three roles the palette assigns everywhere:
 * structure, watchfulness, brand.
 */
export function BeaconMark({ className, lampClass = 'text-bne-ochre' }: BeaconMarkProps) {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      className={cn('text-bne-ink', className)}
      aria-hidden="true"
    >
      {/* tower */}
      <path
        d="M9.4 21 L10.6 10.5 H13.4 L14.6 21"
        stroke="currentColor"
        strokeWidth="1.6"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      {/* gallery deck */}
      <path
        d="M9.2 10.5 H14.8"
        stroke="currentColor"
        strokeWidth="1.6"
        strokeLinecap="round"
      />
      {/* lamp room */}
      <path
        d="M10.4 10.5 V7.2 H13.6 V10.5"
        stroke="currentColor"
        strokeWidth="1.6"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      {/* lamp */}
      <circle cx="12" cy="8.85" r="1.05" className={lampClass} fill="currentColor" />
      {/* base rule */}
      <path
        d="M7.5 21 H16.5"
        stroke="currentColor"
        strokeWidth="1.6"
        strokeLinecap="round"
      />
      {/* signal arcs — left */}
      <path
        d="M8.6 5.6 A5.6 5.6 0 0 0 8.6 12.2"
        stroke="currentColor"
        strokeWidth="1.4"
        strokeLinecap="round"
        className="text-bne-pine"
      />
      <path
        d="M6.3 4.2 A8.4 8.4 0 0 0 6.3 13.6"
        stroke="currentColor"
        strokeWidth="1.4"
        strokeLinecap="round"
        opacity="0.55"
        className="text-bne-pine"
      />
      {/* signal arcs — right */}
      <path
        d="M15.4 5.6 A5.6 5.6 0 0 1 15.4 12.2"
        stroke="currentColor"
        strokeWidth="1.4"
        strokeLinecap="round"
        className="text-bne-pine"
      />
      <path
        d="M17.7 4.2 A8.4 8.4 0 0 1 17.7 13.6"
        stroke="currentColor"
        strokeWidth="1.4"
        strokeLinecap="round"
        opacity="0.55"
        className="text-bne-pine"
      />
    </svg>
  )
}

export interface WordmarkProps {
  className?: string
  subtitle?: ReactNode
}

/**
 * The wordmark: serif BEACON, tracked, over the platform's full name as a
 * micro label. Used in the header and on report-style page furniture.
 */
export function Wordmark({ className, subtitle = 'Banking Early-Alert Network' }: WordmarkProps) {
  return (
    <div className={cn('select-none', className)}>
      <span className="font-display text-[19px] font-semibold leading-none tracking-brand text-bne-ink">
        BEACON
      </span>
      <span className="bne-micro mt-1 block text-[9.5px] leading-none">
        {subtitle}
      </span>
    </div>
  )
}

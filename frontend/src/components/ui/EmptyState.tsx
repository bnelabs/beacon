import { type ReactNode } from 'react'
import { cn } from '../../utils/cn'

/**
 * The designed absence. Every empty or degraded widget on the panel renders
 * this instead of an error wall: no red borders, no provider messages, no
 * "API key required" -- an operator without keys sees what to do next, not
 * what is broken. Errors that are genuine failures (non-2xx with a typed
 * detail) still surface through ErrorMessage where a human must act.
 */
export interface EmptyStateProps {
  title?: ReactNode
  hint?: ReactNode
  action?: ReactNode
  className?: string
  compact?: boolean
}

export default function EmptyState({
  title,
  hint,
  action,
  className,
  compact = false
}: EmptyStateProps) {
  return (
    <div
      className={cn(
        'flex flex-col items-center justify-center text-center rounded-md border border-dashed border-bne-line-strong bg-bne-paper-raise/60',
        compact ? 'px-4 py-6' : 'px-6 py-10',
        className
      )}
    >
      <svg className={cn('text-bne-faint', compact ? 'w-6 h-6' : 'w-8 h-8')} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.4}>
        <path strokeLinecap="round" strokeLinejoin="round" d="M12 3v3m0 12v3m9-9h-3M6 12H3m14.5-5.5l-2 2m-7 7l-2 2m11 0l-2-2m-7-7l-2-2" />
      </svg>
      <p className={cn('mt-3 font-display font-semibold text-bne-ink', compact ? 'text-sm' : 'text-base')}>
        {title}
      </p>
      {hint && <p className="mt-1 max-w-sm text-xs leading-relaxed text-bne-muted">{hint}</p>}
      {action && <div className="mt-4">{action}</div>}
    </div>
  )
}

import { type ButtonHTMLAttributes, type ReactNode } from 'react'
import { cn } from '../../utils/cn'

/**
 * Buttons: flat fills and hairline outlines — no gradients, no glows.
 * The primary action carries the brand pine; destructive actions carry clay;
 * everything else stays quiet so the page reads as a document, not a dashboard.
 */
const variants = {
  primary:
    'bg-bne-pine text-bne-chalk hover:bg-bne-pine-600 active:bg-bne-pine-700 shadow-bne-panel',
  secondary:
    'bg-bne-card text-bne-ink border border-bne-line-strong hover:bg-bne-paper-dim active:bg-bne-line-soft',
  success:
    'bg-bne-moss text-bne-chalk hover:bg-bne-moss-600 active:bg-bne-moss-600 shadow-bne-panel',
  danger:
    'bg-bne-clay text-bne-chalk hover:bg-bne-clay-600 active:bg-bne-clay-700 shadow-bne-panel',
  ghost:
    'bg-transparent text-bne-muted hover:bg-bne-paper-dim hover:text-bne-ink active:bg-bne-line-soft',
  outline:
    'border border-bne-pine text-bne-pine bg-transparent hover:bg-bne-pine-50 active:bg-bne-pine-100'
}

const sizes = {
  sm: 'px-3 py-1.5 text-[13px]',
  md: 'px-4 py-2 text-sm',
  lg: 'px-6 py-2.5 text-[15px]'
}

export type ButtonVariant = keyof typeof variants
export type ButtonSize = keyof typeof sizes

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  children?: ReactNode
  variant?: ButtonVariant
  size?: ButtonSize
  loading?: boolean
}

export default function Button({
  children,
  variant = 'primary',
  size = 'md',
  disabled = false,
  loading = false,
  className,
  ...props
}: ButtonProps) {
  return (
    <button
      className={cn(
        'rounded-md font-medium transition-colors duration-150',
        'disabled:opacity-50 disabled:cursor-not-allowed',
        'focus:outline-none focus-visible:ring-2 focus-visible:ring-bne-pine focus-visible:ring-offset-2 focus-visible:ring-offset-bne-paper',
        variants[variant] || variants.primary,
        sizes[size] || sizes.md,
        className
      )}
      disabled={disabled || loading}
      {...props}
    >
      {loading ? (
        <span className="flex items-center gap-2">
          <svg className="animate-spin h-4 w-4" viewBox="0 0 24 24">
            <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" fill="none" />
            <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z" />
          </svg>
          {children}
        </span>
      ) : (
        children
      )}
    </button>
  )
}

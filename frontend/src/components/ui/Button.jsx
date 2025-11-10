import { cn } from '../../utils/cn'

const variants = {
  primary: 'bg-bne-azure text-white hover:bg-bne-azure-600 active:bg-bne-azure-600',
  secondary: 'bg-bne-steel text-white hover:bg-opacity-90 active:bg-opacity-80',
  success: 'bg-bne-emerald text-white hover:bg-bne-emerald-600 active:bg-bne-emerald-600',
  danger: 'bg-bne-crimson text-white hover:bg-bne-crimson-600 active:bg-bne-crimson-600',
  ghost: 'bg-transparent text-bne-ink hover:bg-bne-ice active:bg-bne-frost',
  outline: 'border-2 border-bne-azure text-bne-azure hover:bg-bne-azure hover:text-white'
}

const sizes = {
  sm: 'px-3 py-1.5 text-sm',
  md: 'px-4 py-2 text-base',
  lg: 'px-6 py-3 text-lg'
}

export default function Button({
  children,
  variant = 'primary',
  size = 'md',
  disabled = false,
  loading = false,
  className,
  ...props
}) {
  return (
    <button
      className={cn(
        'rounded-lg font-medium transition-all duration-200',
        'disabled:opacity-50 disabled:cursor-not-allowed',
        'focus:outline-none focus:ring-2 focus:ring-bne-azure focus:ring-offset-2',
        variants[variant],
        sizes[size],
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

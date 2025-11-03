import { cn } from '../../lib/utils/cn'

const variants = {
  default: 'bg-bne-frost text-bne-steel',
  primary: 'bg-bne-azure/10 text-bne-azure border border-bne-azure/20',
  success: 'bg-bne-emerald/10 text-bne-emerald border border-bne-emerald/20',
  warning: 'bg-bne-amber/10 text-bne-amber border border-bne-amber/20',
  danger: 'bg-bne-crimson/10 text-bne-crimson border border-bne-crimson/20',
  info: 'bg-bne-sky/10 text-bne-sky border border-bne-sky/20'
}

const sizes = {
  sm: 'px-2 py-0.5 text-xs',
  md: 'px-2.5 py-1 text-sm',
  lg: 'px-3 py-1.5 text-base'
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
        'inline-flex items-center rounded-full font-medium',
        variants[variant],
        sizes[size],
        className
      )}
      {...props}
    >
      {children}
    </span>
  )
}

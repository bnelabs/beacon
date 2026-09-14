import { forwardRef } from 'react'
import { cn } from '../../utils/cn'

/**
 * The panel is the unit of the layout: warm card stock, a hairline rule,
 * a small radius and almost no shadow. Depth comes from the border.
 *
 * `accent` draws a 2px rule across the top in a named tone — used for the
 * risk cards on the dashboard so a panel's severity is legible before its
 * numbers are read.
 */
const accents = {
  pine: 'before:bg-bne-pine',
  moss: 'before:bg-bne-moss',
  ochre: 'before:bg-bne-ochre',
  rust: 'before:bg-bne-rust',
  clay: 'before:bg-bne-clay',
  stone: 'before:bg-bne-stone'
}

const Card = forwardRef(function Card(
  { children, className, hover = false, accent = null, as = 'div', ...props },
  ref
) {
  const Component = as

  return (
    <Component
      ref={ref}
      className={cn(
        'relative bg-bne-card rounded-md shadow-bne-panel p-5',
        'border border-bne-line',
        accent && cn('overflow-hidden before:absolute before:inset-x-0 before:top-0 before:h-[2px]', accents[accent]),
        hover && 'transition-shadow duration-150 hover:shadow-bne-card hover:border-bne-line-strong',
        className
      )}
      {...props}
    >
      {children}
    </Component>
  )
})

export default Card

export function CardHeader({ children, className, ...props }) {
  return (
    <div
      className={cn('mb-4 pb-3 border-b border-bne-line-soft', className)}
      {...props}
    >
      {children}
    </div>
  )
}

export function CardTitle({ children, className, ...props }) {
  return (
    <h3
      className={cn('font-display text-[17px] font-semibold leading-snug text-bne-ink', className)}
      {...props}
    >
      {children}
    </h3>
  )
}

export function CardContent({ children, className, ...props }) {
  return (
    <div className={cn('space-y-4', className)} {...props}>
      {children}
    </div>
  )
}

export function CardFooter({ children, className, ...props }) {
  return (
    <div
      className={cn('mt-4 pt-4 border-t border-bne-line-soft flex gap-2', className)}
      {...props}
    >
      {children}
    </div>
  )
}

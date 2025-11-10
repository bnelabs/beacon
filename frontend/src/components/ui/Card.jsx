import { forwardRef } from 'react'
import { cn } from '../../utils/cn'

const Card = forwardRef(function Card({ children, className, hover = false, as = 'div', ...props }, ref) {
  const Component = as

  return (
    <Component
      ref={ref}
      className={cn(
        'bg-white rounded-2xl shadow-bne-panel p-6',
        'border border-bne-frost',
        hover && 'transition-all duration-200 hover:shadow-bne-card hover:-translate-y-0.5',
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
      className={cn('mb-4 pb-4 border-b border-bne-frost', className)}
      {...props}
    >
      {children}
    </div>
  )
}

export function CardTitle({ children, className, ...props }) {
  return (
    <h3
      className={cn('text-lg font-semibold text-bne-ink', className)}
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
      className={cn('mt-4 pt-4 border-t border-bne-frost flex gap-2', className)}
      {...props}
    >
      {children}
    </div>
  )
}

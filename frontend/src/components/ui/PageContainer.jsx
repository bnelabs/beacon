import { cn } from '../../lib/utils/cn'

export default function PageContainer({ children, title, actions, className }) {
  return (
    <div className={cn('p-6', className)}>
      {(title || actions) && (
        <div className="mb-6 flex items-center justify-between">
          {title && (
            <h2 className="text-2xl font-semibold text-bne-ink">{title}</h2>
          )}
          {actions && <div className="flex items-center gap-2">{actions}</div>}
        </div>
      )}
      {children}
    </div>
  )
}

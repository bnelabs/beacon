import { cn } from '../../utils/cn'
import Breadcrumbs from '../Breadcrumbs'

export default function PageContainer({ children, title, subtitle, actions, className }) {
  return (
    <div className={cn('p-6', className)}>
      <div className="mb-6">
        <Breadcrumbs />
        {(title || actions) && (
          <div className="mt-3 flex items-center justify-between">
            <div>
              {title && (
                <h2 className="text-2xl font-semibold text-bne-ink">{title}</h2>
              )}
              {subtitle && (
                <p className="text-sm text-bne-steel mt-1">{subtitle}</p>
              )}
            </div>
            {actions && <div className="flex items-center gap-2">{actions}</div>}
          </div>
        )}
      </div>
      {children}
    </div>
  )
}

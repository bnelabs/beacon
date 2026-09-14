import { cn } from '../../utils/cn'
import Breadcrumbs from '../Breadcrumbs'

/**
 * Page frame: breadcrumbs, then a serif title over a hairline rule — the
 * masthead of a printed brief. `eyebrow` renders the tracked micro label
 * above the title for the section name.
 */
export default function PageContainer({ children, title, subtitle, eyebrow, actions, className }) {
  return (
    <div className={cn('px-7 py-6', className)}>
      <div className="mb-7">
        <Breadcrumbs />
        {(title || actions) && (
          <div className="mt-3 flex items-end justify-between gap-6 border-b border-bne-line pb-4">
            <div className="min-w-0">
              {eyebrow && <p className="bne-micro mb-1.5">{eyebrow}</p>}
              {title && (
                <h2 className="font-display text-[26px] font-semibold leading-tight tracking-tight text-bne-ink">
                  {title}
                </h2>
              )}
              {subtitle && (
                <p className="text-[13.5px] leading-relaxed text-bne-muted mt-1.5 max-w-3xl">
                  {subtitle}
                </p>
              )}
            </div>
            {actions && <div className="flex items-center gap-2 shrink-0 pb-0.5">{actions}</div>}
          </div>
        )}
      </div>
      {children}
    </div>
  )
}

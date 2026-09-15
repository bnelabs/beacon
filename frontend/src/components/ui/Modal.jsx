import { useEffect, useRef } from 'react'
import { useFocusTrap } from '../../hooks/useFocusTrap'
import { createPortal } from 'react-dom'
import { cn } from '../../utils/cn'

/**
 * Lightweight modal overlay used across dashboard pages.
 * Renders into document.body via a portal and handles escape/overlay close.
 */
export default function Modal({
  isOpen,
  onClose,
  title,
  children,
  footer,
  widthClass = 'max-w-2xl'
}) {
  const panelRef = useRef(null)
  // The trap owns Escape as well as Tab, so the keyboard story lives in one
  // place instead of half here and half in the hook.
  useFocusTrap(panelRef, isOpen, onClose)

  useEffect(() => {
    if (!isOpen) {
      return
    }

    // Prevent scrolling the background while modal is open.
    const originalOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'

    return () => {
      document.body.style.overflow = originalOverflow
    }
  }, [isOpen])

  if (!isOpen || typeof document === 'undefined') {
    return null
  }

  return createPortal(
    <div className="fixed inset-0 z-50 flex items-center justify-center px-4">
      <div
        className="absolute inset-0 bg-bne-ink/60"
        onClick={() => onClose?.()}
        role="presentation"
      />
      <div
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-label={typeof title === 'string' ? title : undefined}
        className={cn(
          'relative z-10 w-full rounded-md bg-bne-card shadow-bne-lift',
          'border border-bne-line',
          widthClass
        )}
      >
        <div className="flex items-center justify-between px-6 py-4 border-b border-bne-line">
          <h2 className="font-display text-xl font-semibold text-bne-ink">{title}</h2>
          <button
            type="button"
            onClick={() => onClose?.()}
            className="rounded-full p-2 text-bne-muted hover:bg-bne-paper focus:outline-none focus:ring-2 focus:ring-bne-pine"
            aria-label="Close modal"
          >
            <svg className="h-5 w-5" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2} fill="none">
              <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>

        <div className="px-6 py-5 max-h-[70vh] overflow-y-auto">{children}</div>

        {footer && (
          <div className="flex items-center justify-end gap-3 px-6 py-4 border-t border-bne-line bg-bne-paper/50 rounded-b-2xl">
            {footer}
          </div>
        )}
      </div>
    </div>,
    document.body
  )
}

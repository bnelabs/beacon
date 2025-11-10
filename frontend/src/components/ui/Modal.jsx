import { useEffect } from 'react'
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
  useEffect(() => {
    if (!isOpen) {
      return
    }

    function handleKeyDown(event) {
      if (event.key === 'Escape') {
        onClose?.()
      }
    }

    document.addEventListener('keydown', handleKeyDown)
    // Prevent scrolling the background while modal is open.
    const originalOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'

    return () => {
      document.removeEventListener('keydown', handleKeyDown)
      document.body.style.overflow = originalOverflow
    }
  }, [isOpen, onClose])

  if (!isOpen || typeof document === 'undefined') {
    return null
  }

  return createPortal(
    <div className="fixed inset-0 z-50 flex items-center justify-center px-4">
      <div
        className="absolute inset-0 bg-bne-ink/60 backdrop-blur-sm"
        onClick={() => onClose?.()}
        role="presentation"
      />
      <div
        className={cn(
          'relative z-10 w-full rounded-2xl bg-white shadow-2xl',
          'border border-bne-frost',
          widthClass
        )}
      >
        <div className="flex items-center justify-between px-6 py-4 border-b border-bne-frost">
          <h2 className="text-xl font-semibold text-bne-ink">{title}</h2>
          <button
            type="button"
            onClick={() => onClose?.()}
            className="rounded-full p-2 text-bne-steel hover:bg-bne-ice focus:outline-none focus:ring-2 focus:ring-bne-azure"
            aria-label="Close modal"
          >
            <svg className="h-5 w-5" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2} fill="none">
              <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>

        <div className="px-6 py-5 max-h-[70vh] overflow-y-auto">{children}</div>

        {footer && (
          <div className="flex items-center justify-end gap-3 px-6 py-4 border-t border-bne-frost bg-bne-ice/50 rounded-b-2xl">
            {footer}
          </div>
        )}
      </div>
    </div>,
    document.body
  )
}

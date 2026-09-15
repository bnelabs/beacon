import { useEffect } from 'react'

const FOCUSABLE = [
  'a[href]',
  'button:not([disabled])',
  'input:not([disabled])',
  'select:not([disabled])',
  'textarea:not([disabled])',
  '[tabindex]:not([tabindex="-1"])'
].join(', ')

/**
 * Keep keyboard focus inside an open overlay, and return it on close.
 *
 * why: modals and drawers closed on Escape but never trapped Tab, so a
 * keyboard user tabbing "forward" left the dialog and wandered the page
 * behind it -- through content the overlay was supposed to be modal to--
 * and focus was dropped on the body when the overlay unmounted. Trapping is
 * the difference between an overlay and a suggestion.
 *
 * @param ref      ref to the overlay's root element
 * @param isActive whether the overlay is currently open
 * @param onClose  called on Escape, so the trap owns the whole keyboard story
 */
export function useFocusTrap(ref, isActive, onClose) {
  useEffect(() => {
    if (!isActive) return undefined

    const node = ref.current
    const previouslyFocused =
      typeof document !== 'undefined' ? document.activeElement : null

    function focusables() {
      if (!node) return []
      return Array.from(node.querySelectorAll(FOCUSABLE)).filter(
        (element) => element.getClientRects().length > 0
      )
    }

    // Land on the first control rather than the overlay chrome.
    const initial = focusables()[0]
    if (initial) initial.focus()

    function handleKeyDown(event) {
      if (event.key === 'Escape') {
        event.stopPropagation()
        onClose?.()
        return
      }
      if (event.key !== 'Tab') return
      const items = focusables()
      if (items.length === 0) {
        event.preventDefault()
        return
      }
      const first = items[0]
      const last = items[items.length - 1]
      const active = document.activeElement
      if (event.shiftKey && (active === first || !node.contains(active))) {
        event.preventDefault()
        last.focus()
      } else if (!event.shiftKey && (active === last || !node.contains(active))) {
        event.preventDefault()
        first.focus()
      }
    }

    document.addEventListener('keydown', handleKeyDown, true)
    return () => {
      document.removeEventListener('keydown', handleKeyDown, true)
      if (previouslyFocused && typeof previouslyFocused.focus === 'function') {
        previouslyFocused.focus()
      }
    }
  }, [ref, isActive, onClose])
}

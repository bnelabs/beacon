import { useEffect, useRef, useState } from 'react'
import { useRouter } from '../../store/useRouter'
import NotificationBell from '../NotificationBell'

export default function Header() {
  const [isProfileMenuOpen, setIsProfileMenuOpen] = useState(false)
  const profileRef = useRef(null)
  const { navigate } = useRouter()

  useEffect(() => {
    function handleClickOutside(event) {
      if (profileRef.current && !profileRef.current.contains(event.target)) {
        setIsProfileMenuOpen(false)
      }
    }

    function handleEscape(event) {
      if (event.key === 'Escape') {
        setIsProfileMenuOpen(false)
      }
    }

    document.addEventListener('mousedown', handleClickOutside)
    document.addEventListener('keydown', handleEscape)

    return () => {
      document.removeEventListener('mousedown', handleClickOutside)
      document.removeEventListener('keydown', handleEscape)
    }
  }, [])

  const handleNavigate = (page) => {
    navigate(page)
    setIsProfileMenuOpen(false)
  }

  return (
    <header className="h-16 bg-white border-b border-bne-frost flex items-center px-6 sticky top-0 z-40">
      <div className="flex items-center justify-between w-full">
        <div className="flex items-center gap-3">
          <div className="w-8 h-8 bg-gradient-to-br from-bne-azure to-bne-indigo rounded-lg flex items-center justify-center">
            <span className="text-white font-bold text-sm">B</span>
          </div>
          <div>
            <h1 className="text-lg font-semibold text-bne-ink">BEACON</h1>
            <p className="text-xs text-bne-steel -mt-0.5">Banking Network Engine</p>
          </div>
        </div>

        <div className="flex items-center gap-3">
          <button
            type="button"
            onClick={() => {
              const event = new KeyboardEvent('keydown', {
                key: 'k',
                metaKey: true,
                bubbles: true
              })
              document.dispatchEvent(event)
            }}
            data-tour="search-button"
            className="hidden sm:flex items-center gap-2 px-3 py-1.5 text-sm text-bne-steel hover:text-bne-ink bg-bne-ice hover:bg-bne-frost rounded-lg transition-colors border border-bne-frost"
          >
            <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
            </svg>
            <span>Search</span>
            <kbd className="px-1.5 py-0.5 text-xs font-mono bg-white rounded border border-bne-frost">⌘K</kbd>
          </button>

          <NotificationBell />

          <div className="relative" ref={profileRef}>
            <button
              type="button"
              onClick={() => {
                setIsProfileMenuOpen((previous) => !previous)
                setIsNotificationsOpen(false)
              }}
              className="h-8 w-8 bg-bne-azure rounded-full flex items-center justify-center text-white text-sm font-medium hover:ring-2 hover:ring-bne-azure focus:outline-none focus:ring-2 focus:ring-bne-azure"
              aria-haspopup="menu"
              aria-expanded={isProfileMenuOpen}
              aria-label="Open user menu"
            >
              U
            </button>

            {isProfileMenuOpen && (
              <div
                className="absolute right-0 mt-2 w-52 rounded-xl bg-white shadow-bne-card border border-bne-frost py-2 z-20"
                role="menu"
                aria-label="User actions"
              >
                <button
                  type="button"
                  onClick={() => handleNavigate('settings')}
                  className="w-full text-left px-4 py-2 text-sm text-bne-ink hover:bg-bne-frost transition-colors"
                  role="menuitem"
                >
                  Settings
                </button>
                <button
                  type="button"
                  onClick={() => handleNavigate('help')}
                  className="w-full text-left px-4 py-2 text-sm text-bne-ink hover:bg-bne-frost transition-colors"
                  role="menuitem"
                >
                  Help Center
                </button>
                <div className="border-t border-bne-frost my-1" />
                <button
                  type="button"
                  disabled
                  className="w-full text-left px-4 py-2 text-sm text-bne-steel/70 cursor-not-allowed"
                  role="menuitem"
                  aria-disabled="true"
                >
                  Sign out (coming soon)
                </button>
              </div>
            )}
          </div>
        </div>
      </div>
    </header>
  )
}

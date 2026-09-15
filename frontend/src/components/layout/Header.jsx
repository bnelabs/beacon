import { useEffect, useRef, useState } from 'react'
import { useRouter } from '../../store/useRouter'
import NotificationBell from '../NotificationBell'
import { BeaconMark, Wordmark } from '../Brand'
import { API_TOKEN_KEY } from '../../utils/apiClient'

export default function Header() {
  const [isProfileMenuOpen, setIsProfileMenuOpen] = useState(false)
  const [hasStoredToken, setHasStoredToken] = useState(
    () => Boolean(window.localStorage.getItem(API_TOKEN_KEY))
  )
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
    <header className="h-16 bg-bne-card border-b border-bne-line flex items-center px-6 sticky top-0 z-40">
      <div className="flex items-center justify-between w-full">
        <div className="flex items-center gap-3.5">
          <div className="w-9 h-9 rounded-md border border-bne-line bg-bne-paper flex items-center justify-center">
            <BeaconMark className="w-6 h-6" />
          </div>
          <Wordmark />
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
            className="hidden sm:flex items-center gap-2 px-3 py-1.5 text-sm text-bne-muted hover:text-bne-ink bg-bne-paper hover:bg-bne-paper-dim rounded-md transition-colors border border-bne-line"
          >
            <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.8}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
            </svg>
            <span>Search</span>
            <kbd className="px-1.5 py-0.5 text-[10px] font-mono bg-bne-card rounded-[3px] border border-bne-line text-bne-faint">⌘K</kbd>
          </button>

          <NotificationBell />

          <div className="relative" ref={profileRef}>
            <button
              type="button"
              onClick={() => setIsProfileMenuOpen((previous) => !previous)}
              className="h-8 w-8 bg-bne-pine rounded-md flex items-center justify-center text-bne-chalk text-sm font-medium hover:bg-bne-pine-600 focus:outline-none focus-visible:ring-2 focus-visible:ring-bne-pine focus-visible:ring-offset-2 focus-visible:ring-offset-bne-card"
              aria-haspopup="menu"
              aria-expanded={isProfileMenuOpen}
              aria-label="Open user menu"
            >
              U
            </button>

            {isProfileMenuOpen && (
              <div
                className="absolute right-0 mt-2 w-52 rounded-md bg-bne-card shadow-bne-lift border border-bne-line py-1.5 z-20"
                role="menu"
                aria-label="User actions"
              >
                <button
                  type="button"
                  onClick={() => handleNavigate('settings')}
                  className="w-full text-left px-4 py-2 text-sm text-bne-ink hover:bg-bne-paper-dim transition-colors"
                  role="menuitem"
                >
                  Settings
                </button>
                <button
                  type="button"
                  onClick={() => handleNavigate('help')}
                  className="w-full text-left px-4 py-2 text-sm text-bne-ink hover:bg-bne-paper-dim transition-colors"
                  role="menuitem"
                >
                  Help Center
                </button>
                <div className="border-t border-bne-line my-1" />
                {hasStoredToken ? (
                  <button
                    type="button"
                    className="w-full text-left px-4 py-2 text-sm text-bne-ink hover:bg-bne-paper-dim transition-colors"
                    role="menuitem"
                    onClick={() => {
                      window.localStorage.removeItem(API_TOKEN_KEY)
                      setHasStoredToken(false)
                      window.location.reload()
                    }}
                  >
                    Sign out — clears this browser's token
                  </button>
                ) : (
                  <button
                    type="button"
                    disabled
                    className="w-full text-left px-4 py-2 text-sm text-bne-faint cursor-not-allowed"
                    role="menuitem"
                    aria-disabled="true"
                  >
                    Sign out — no token in this browser
                  </button>
                )}
              </div>
            )}
          </div>
        </div>
      </div>
    </header>
  )
}

import { useEffect, useRef, useState } from 'react'
import { useRouter } from '../../store/useRouter'

export default function Header() {
  const [isNotificationsOpen, setIsNotificationsOpen] = useState(false)
  const [isProfileMenuOpen, setIsProfileMenuOpen] = useState(false)
  const notificationsRef = useRef(null)
  const profileRef = useRef(null)
  const { navigate } = useRouter()

  useEffect(() => {
    function handleClickOutside(event) {
      if (notificationsRef.current && !notificationsRef.current.contains(event.target)) {
        setIsNotificationsOpen(false)
      }
      if (profileRef.current && !profileRef.current.contains(event.target)) {
        setIsProfileMenuOpen(false)
      }
    }

    function handleEscape(event) {
      if (event.key === 'Escape') {
        setIsNotificationsOpen(false)
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
    setIsNotificationsOpen(false)
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
          <div className="relative" ref={notificationsRef}>
            <button
              type="button"
              onClick={() => {
                setIsNotificationsOpen((previous) => !previous)
                setIsProfileMenuOpen(false)
              }}
              className="p-2 hover:bg-bne-frost rounded-lg transition-colors focus:outline-none focus:ring-2 focus:ring-bne-azure"
              aria-haspopup="dialog"
              aria-expanded={isNotificationsOpen}
              aria-label="View notifications"
            >
              <svg className="w-5 h-5 text-bne-steel" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 17h5l-1.405-1.405A2.032 2.032 0 0118 14.158V11a6.002 6.002 0 00-4-5.659V5a2 2 0 10-4 0v.341C7.67 6.165 6 8.388 6 11v3.159c0 .538-.214 1.055-.595 1.436L4 17h5m6 0v1a3 3 0 11-6 0v-1m6 0H9" />
              </svg>
            </button>

            {isNotificationsOpen && (
              <div
                className="absolute right-0 mt-2 w-72 rounded-xl bg-white shadow-bne-card border border-bne-frost overflow-hidden z-20"
                role="dialog"
                aria-label="Notifications"
              >
                <div className="flex items-center justify-between px-4 py-3 border-b border-bne-frost bg-bne-ice/30">
                  <span className="text-sm font-semibold text-bne-ink">Notifications</span>
                  <button
                    type="button"
                    onClick={() => setIsNotificationsOpen(false)}
                    className="text-xs font-medium text-bne-steel hover:text-bne-ink transition-colors"
                  >
                    Close
                  </button>
                </div>
                <div className="px-4 py-5 text-sm text-bne-steel space-y-3">
                  <p className="font-medium text-bne-ink">You&rsquo;re all caught up</p>
                  <p>
                    Beacon will surface alerts here when data pipelines run, models complete training,
                    or risk thresholds are crossed. Keep the app running to stay informed in real-time.
                  </p>
                </div>
              </div>
            )}
          </div>

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

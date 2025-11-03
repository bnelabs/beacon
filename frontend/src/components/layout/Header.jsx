export default function Header() {
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

        <div className="flex items-center gap-4">
          <button className="p-2 hover:bg-bne-frost rounded-lg transition-colors">
            <svg className="w-5 h-5 text-bne-steel" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 17h5l-1.405-1.405A2.032 2.032 0 0118 14.158V11a6.002 6.002 0 00-4-5.659V5a2 2 0 10-4 0v.341C7.67 6.165 6 8.388 6 11v3.159c0 .538-.214 1.055-.595 1.436L4 17h5m6 0v1a3 3 0 11-6 0v-1m6 0H9" />
            </svg>
          </button>

          <div className="h-8 w-8 bg-bne-azure rounded-full flex items-center justify-center">
            <span className="text-white text-sm font-medium">U</span>
          </div>
        </div>
      </div>
    </header>
  )
}

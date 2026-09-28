import { type ReactNode, useState } from 'react'
import Header from './Header'
import Sidebar from './Sidebar'
import GlobalSearch from '../GlobalSearch'
import ErrorBoundary from '../ErrorBoundary'
import { useRouter } from '../../store/useRouter'

export interface LayoutProps {
  children?: ReactNode
}

export default function Layout({ children }: LayoutProps) {
  const { currentPage } = useRouter()
  const [sidebarOpen, setSidebarOpen] = useState(false)
  return (
    <div className="flex flex-col md:flex-row h-screen bg-bne-paper overflow-hidden">
      {/* Mobile sidebar overlay */}
      {sidebarOpen && (
        <div className="fixed inset-0 z-50 md:hidden">
          <div className="absolute inset-0 bg-bne-ink/50" onClick={() => setSidebarOpen(false)} />
          <div className="absolute left-0 top-0 h-full w-64 bg-bne-card border-r border-bne-line shadow-xl">
            <Sidebar />
          </div>
        </div>
      )}
      <div className="hidden md:flex">
        <Sidebar />
      </div>
      <div className="flex-1 flex flex-col overflow-hidden">
        {/* Mobile header with hamburger */}
        <div className="md:hidden flex items-center gap-3 px-4 h-16 border-b border-bne-line bg-bne-card">
          <button
            aria-label="Open menu"
            onClick={() => setSidebarOpen(true)}
            className="p-2 rounded-md hover:bg-bne-paper-dim"
          >
            <svg className="w-6 h-6" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M4 6h16M4 12h16M4 18h16" />
            </svg>
          </button>
          <span className="font-display text-lg">Systemic Liquidity Risk</span>
        </div>
        <Header />
        <main className="flex-1 overflow-y-auto">
          {/* Keyed by page so a failed view resets when the operator moves on. */}
          <ErrorBoundary key={currentPage || 'page'}>
            {children}
          </ErrorBoundary>
        </main>
      </div>
      <GlobalSearch />
    </div>
  )
}

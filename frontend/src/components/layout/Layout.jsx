import Header from './Header'
import Sidebar from './Sidebar'
import GlobalSearch from '../GlobalSearch'
import ErrorBoundary from '../ErrorBoundary'
import { useRouter } from '../../store/useRouter'

export default function Layout({ children }) {
  const { currentPage } = useRouter()
  return (
    <div className="flex h-screen bg-bne-paper overflow-hidden">
      <Sidebar />
      <div className="flex-1 flex flex-col overflow-hidden">
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

import { lazy, Suspense, useEffect, useState } from 'react'
import Modal from './components/ui/Modal'
import Button from './components/ui/Button'
import { API_TOKEN_KEY } from './utils/apiClient'
import Layout from './components/layout/Layout'
import Dashboard from './pages/Dashboard'
import LoadingSpinner from './components/ui/LoadingSpinner'
import { useRouter } from './store/useRouter'

// Lazy load heavy components to reduce initial bundle size
const RiskMapPage = lazy(() => import('./pages/RiskMapPage'))
const Models = lazy(() => import('./pages/Models'))
const Jobs = lazy(() => import('./pages/Jobs'))
const Results = lazy(() => import('./pages/Results'))
const DataSources = lazy(() => import('./pages/DataSources'))
const CountryProfiles = lazy(() => import('./pages/CountryProfiles'))
const ModelPerformance = lazy(() => import('./pages/ModelPerformance'))
const DataQuality = lazy(() => import('./pages/DataQuality'))
const Analytics = lazy(() => import('./pages/Analytics'))
const Settings = lazy(() => import('./pages/Settings'))

export default function App() {
  const { currentPage, params } = useRouter()
  const [tokenRequired, setTokenRequired] = useState(false)
  const [tokenDraft, setTokenDraft] = useState('')

  useEffect(() => {
    const onUnauthorized = () => setTokenRequired(true)
    window.addEventListener('beacon:unauthorized', onUnauthorized)
    return () => window.removeEventListener('beacon:unauthorized', onUnauthorized)
  }, [])

  const saveToken = () => {
    try {
      window.localStorage.setItem(API_TOKEN_KEY, tokenDraft.trim())
    } catch {
      // storage unavailable: the token will not survive a reload
    }
    setTokenRequired(false)
    window.location.reload()
  }

  const renderPage = () => {
    const PageComponent = (() => {
      switch (currentPage) {
        case 'dashboard':
          return Dashboard
        case 'globe':
          return RiskMapPage
        case 'models':
          return Models
        case 'jobs':
          return Jobs
        case 'results':
          return Results
        case 'datasources':
          return DataSources
        case 'countries':
          return CountryProfiles
        case 'performance':
          return ModelPerformance
        case 'data-quality':
          return DataQuality
        case 'analytics':
          return Analytics
        case 'settings':
          return Settings
        default:
          return Dashboard
      }
    })()

    // Dashboard is not lazy-loaded, render directly
    if (currentPage === 'dashboard' || !currentPage) {
      return <PageComponent params={params} />
    }

    // All other pages are lazy-loaded with suspense
    return (
      <Suspense
        fallback={
          <div className="flex items-center justify-center h-screen">
            <LoadingSpinner message={`Loading ${currentPage}...`} />
          </div>
        }
      >
        <PageComponent params={params} />
      </Suspense>
    )
  }

  return (
    <>
      <Layout>
        {renderPage()}
      </Layout>
      <Modal
        isOpen={tokenRequired}
        onClose={() => setTokenRequired(false)}
        title="This deployment requires an access token"
        footer={
          <>
            <Button type="button" variant="ghost" onClick={() => setTokenRequired(false)}>
              Cancel
            </Button>
            <Button type="button" variant="primary" onClick={saveToken} disabled={!tokenDraft.trim()}>
              Save and reload
            </Button>
          </>
        }
      >
        <p className="text-sm leading-relaxed text-bne-muted">
          The operator set <span className="font-mono text-xs">BEACON_API_TOKEN</span>, so every
          API call must carry it. The token is stored in this browser only and sent as a
          bearer header; it never appears in URLs or logs.
        </p>
        <input
          autoFocus
          type="password"
          className="mt-4 w-full rounded-md border border-bne-line bg-bne-card px-3 py-2 text-sm text-bne-ink"
          value={tokenDraft}
          onChange={(event) => setTokenDraft(event.target.value)}
          placeholder="access token"
        />
      </Modal>
    </>
  )
}

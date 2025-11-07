import { lazy, Suspense } from 'react'
import Layout from './components/layout/Layout'
import Dashboard from './pages/Dashboard'
import LoadingSpinner from './components/ui/LoadingSpinner'
import { useRouter } from './store/useRouter'

// Lazy load heavy components to reduce initial bundle size
const GlobeView = lazy(() => import('./pages/GlobeView'))
const Models = lazy(() => import('./pages/Models'))
const Jobs = lazy(() => import('./pages/Jobs'))
const Results = lazy(() => import('./pages/Results'))
const DataSources = lazy(() => import('./pages/DataSources'))
const CountryProfiles = lazy(() => import('./pages/CountryProfiles'))
const ModelPerformance = lazy(() => import('./pages/ModelPerformance'))
const DataQuality = lazy(() => import('./pages/DataQuality'))
const Analytics = lazy(() => import('./pages/Analytics'))
const Settings = lazy(() => import('./pages/Settings'))
const Help = lazy(() => import('./pages/Help'))

export default function App() {
  const { currentPage, params } = useRouter()

  const renderPage = () => {
    const PageComponent = (() => {
      switch (currentPage) {
        case 'dashboard':
          return Dashboard
        case 'globe':
          return GlobeView
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
        case 'help':
          return Help
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
    <Layout>
      {renderPage()}
    </Layout>
  )
}

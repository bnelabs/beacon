import Layout from './components/layout/Layout'
import Dashboard from './pages/Dashboard'
import GlobeView from './pages/GlobeView'
import Models from './pages/Models'
import Jobs from './pages/Jobs'
import Results from './pages/Results'
import DataSources from './pages/DataSources'
import { useRouter } from './store/useRouter'

export default function App() {
  const { currentPage } = useRouter()

  const renderPage = () => {
    switch (currentPage) {
      case 'dashboard':
        return <Dashboard />
      case 'globe':
        return <GlobeView />
      case 'models':
        return <Models />
      case 'jobs':
        return <Jobs />
      case 'results':
        return <Results />
      case 'datasources':
        return <DataSources />
      default:
        return <Dashboard />
    }
  }

  return (
    <Layout>
      {renderPage()}
    </Layout>
  )
}

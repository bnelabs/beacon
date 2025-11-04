import Layout from './components/layout/Layout'
import Dashboard from './pages/Dashboard'
import GlobeView from './pages/GlobeView'
import Models from './pages/Models'
import Jobs from './pages/Jobs'
import Results from './pages/Results'
import DataSources from './pages/DataSources'
import Settings from './pages/Settings'
import Help from './pages/Help'
import { useRouter } from './store/useRouter'

export default function App() {
  const { currentPage, params } = useRouter()

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
        return <Results params={params} />
      case 'datasources':
        return <DataSources />
      case 'settings':
        return <Settings />
      case 'help':
        return <Help />
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

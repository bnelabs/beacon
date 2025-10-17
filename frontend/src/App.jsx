import { Routes, Route } from 'react-router-dom'
import { Box } from '@mui/material'
import Layout from './components/Layout'
import Dashboard from './pages/Dashboard'
import Catalogue from './pages/Catalogue'
import DataSources from './pages/DataSources'
import Assets from './pages/Assets'
import Jobs from './pages/Jobs'
import Configuration from './pages/Configuration'
import SystemStatus from './pages/SystemStatus'
import ErrorAnalytics from './pages/ErrorAnalytics'
import Results from './pages/Results'

function App() {
  return (
    <Box sx={{ display: 'flex', minHeight: '100vh' }}>
      <Layout>
        <Routes>
          <Route path="/" element={<Dashboard />} />
          <Route path="/catalogue" element={<Catalogue />} />
          <Route path="/data-sources" element={<DataSources />} />
          <Route path="/assets" element={<Assets />} />
          <Route path="/jobs" element={<Jobs />} />
          <Route path="/results" element={<Results />} />
          <Route path="/configuration" element={<Configuration />} />
          <Route path="/system" element={<SystemStatus />} />
          <Route path="/errors" element={<ErrorAnalytics />} />
        </Routes>
      </Layout>
    </Box>
  )
}

export default App

import { Routes, Route } from 'react-router-dom'
import { Box } from '@mui/material'
import Layout from './components/Layout'
import Dashboard from './pages/Dashboard'
import DataSources from './pages/DataSources'
import Assets from './pages/Assets'
import Jobs from './pages/Jobs'
import Configuration from './pages/Configuration'
import SystemStatus from './pages/SystemStatus'

function App() {
  return (
    <Box sx={{ display: 'flex', minHeight: '100vh' }}>
      <Layout>
        <Routes>
          <Route path="/" element={<Dashboard />} />
          <Route path="/data-sources" element={<DataSources />} />
          <Route path="/assets" element={<Assets />} />
          <Route path="/jobs" element={<Jobs />} />
          <Route path="/configuration" element={<Configuration />} />
          <Route path="/system" element={<SystemStatus />} />
        </Routes>
      </Layout>
    </Box>
  )
}

export default App

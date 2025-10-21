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

import { QueryClientProvider } from 'react-query';
import { queryClient } from './api/queryClient';

import { Navigate, Outlet } from 'react-router-dom';
import Login from './pages/Login';

const ProtectedRoute = () => {
  const token = localStorage.getItem('token');
  return token ? <Outlet /> : <Navigate to="/login" />;
};

function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <Box sx={{ display: 'flex', minHeight: '100vh' }}>
        <Routes>
          <Route path="/login" element={<Login />} />
          <Route element={<ProtectedRoute />}>
            <Route path="/" element={<Layout><Dashboard /></Layout>} />
            <Route path="/catalogue" element={<Layout><Catalogue /></Layout>} />
            <Route path="/data-sources" element={<Layout><DataSources /></Layout>} />
            <Route path="/assets" element={<Layout><Assets /></Layout>} />
            <Route path="/jobs" element={<Layout><Jobs /></Layout>} />
            <Route path="/results" element={<Layout><Results /></Layout>} />
            <Route path="/configuration" element={<Layout><Configuration /></Layout>} />
            <Route path="/system" element={<Layout><SystemStatus /></Layout>} />
import Predictions from './pages/Predictions';

            <Route path="/predictions" element={<Layout><Predictions /></Layout>} />
import Experiments from './pages/Experiments';

            <Route path="/experiments" element={<Layout><Experiments /></Layout>} />
            <Route path="/errors" element={<Layout><ErrorAnalytics /></Layout>} />
          </Route>
        </Routes>
      </Box>
    </QueryClientProvider>
  );
}

export default App

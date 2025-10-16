import { useQuery } from 'react-query'
import {
  Box,
  Grid,
  Card,
  CardContent,
  Typography,
  CircularProgress,
  Alert,
  Chip,
} from '@mui/material'
import {
  CheckCircle as CheckCircleIcon,
  Error as ErrorIcon,
  Warning as WarningIcon,
  Info as InfoIcon,
} from '@mui/icons-material'
import { api } from '../api/client'

export default function Dashboard() {
  // Fetch system status
  const { data: systemStatus, isLoading: statusLoading } = useQuery(
    'systemStatus',
    () => api.system.status().then(res => res.data),
    { refetchInterval: 30000 } // Refresh every 30 seconds
  )

  // Fetch data sources
  const { data: dataSources, isLoading: dsLoading } = useQuery(
    'dataSources',
    () => api.dataSources.list().then(res => res.data)
  )

  // Fetch assets
  const { data: assets, isLoading: assetsLoading } = useQuery(
    'assets',
    () => api.assets.list().then(res => res.data)
  )

  // Fetch recent jobs
  const { data: jobs, isLoading: jobsLoading } = useQuery(
    'recentJobs',
    () => api.jobs.list({ limit: 10 }).then(res => res.data),
    { refetchInterval: 5000 } // Refresh every 5 seconds
  )

  if (statusLoading || dsLoading || assetsLoading || jobsLoading) {
    return (
      <Box display="flex" justifyContent="center" alignItems="center" minHeight="400px">
        <CircularProgress />
      </Box>
    )
  }

  // Calculate statistics
  const enabledDataSources = dataSources?.filter(ds => ds.enabled).length || 0
  const totalDataSources = dataSources?.length || 0
  const errorDataSources = dataSources?.filter(ds => ds.status === 'error').length || 0

  const enabledAssets = assets?.filter(a => a.enabled).length || 0
  const totalAssets = assets?.length || 0

  const runningJobs = jobs?.filter(j => j.status === 'running').length || 0
  const recentFailures = jobs?.filter(j => j.status === 'failed').length || 0

  return (
    <Box>
      <Typography variant="h4" gutterBottom>
        Dashboard Overview
      </Typography>
      <Typography variant="body1" color="text.secondary" paragraph>
        Welcome to the Liquidity Monitor. This dashboard shows the current status
        of your financial risk monitoring system.
      </Typography>

      <Grid container spacing={3}>
        {/* System Status Card */}
        <Grid item xs={12} md={6} lg={3}>
          <Card>
            <CardContent>
              <Typography color="text.secondary" gutterBottom>
                System Status
              </Typography>
              <Box display="flex" alignItems="center" gap={1} mb={2}>
                <CheckCircleIcon color="success" />
                <Typography variant="h5">
                  {systemStatus?.status === 'operational' ? 'Operational' : 'Degraded'}
                </Typography>
              </Box>
              <Typography variant="body2" color="text.secondary">
                CPU: {systemStatus?.cpu?.usage_percent}%
              </Typography>
              <Typography variant="body2" color="text.secondary">
                Memory: {systemStatus?.memory?.usage_percent}%
              </Typography>
              {systemStatus?.gpu?.available && (
                <Typography variant="body2" color="text.secondary">
                  GPU: {systemStatus.gpu.devices[0]?.memory_percent}%
                </Typography>
              )}
            </CardContent>
          </Card>
        </Grid>

        {/* Data Sources Card */}
        <Grid item xs={12} md={6} lg={3}>
          <Card>
            <CardContent>
              <Typography color="text.secondary" gutterBottom>
                Data Sources
              </Typography>
              <Box display="flex" alignItems="center" gap={1} mb={2}>
                {errorDataSources > 0 ? (
                  <ErrorIcon color="error" />
                ) : (
                  <CheckCircleIcon color="success" />
                )}
                <Typography variant="h5">
                  {enabledDataSources} / {totalDataSources}
                </Typography>
              </Box>
              <Typography variant="body2" color="text.secondary">
                {enabledDataSources} active sources
              </Typography>
              {errorDataSources > 0 && (
                <Chip
                  label={`${errorDataSources} error${errorDataSources > 1 ? 's' : ''}`}
                  color="error"
                  size="small"
                  sx={{ mt: 1 }}
                />
              )}
            </CardContent>
          </Card>
        </Grid>

        {/* Assets Card */}
        <Grid item xs={12} md={6} lg={3}>
          <Card>
            <CardContent>
              <Typography color="text.secondary" gutterBottom>
                Monitored Assets
              </Typography>
              <Box display="flex" alignItems="center" gap={1} mb={2}>
                <InfoIcon color="info" />
                <Typography variant="h5">
                  {enabledAssets} / {totalAssets}
                </Typography>
              </Box>
              <Typography variant="body2" color="text.secondary">
                {enabledAssets} assets being monitored
              </Typography>
            </CardContent>
          </Card>
        </Grid>

        {/* Jobs Card */}
        <Grid item xs={12} md={6} lg={3}>
          <Card>
            <CardContent>
              <Typography color="text.secondary" gutterBottom>
                Background Jobs
              </Typography>
              <Box display="flex" alignItems="center" gap={1} mb={2}>
                {recentFailures > 0 ? (
                  <WarningIcon color="warning" />
                ) : (
                  <CheckCircleIcon color="success" />
                )}
                <Typography variant="h5">
                  {runningJobs} running
                </Typography>
              </Box>
              <Typography variant="body2" color="text.secondary">
                {jobs?.length || 0} recent jobs
              </Typography>
              {recentFailures > 0 && (
                <Chip
                  label={`${recentFailures} failed`}
                  color="warning"
                  size="small"
                  sx={{ mt: 1 }}
                />
              )}
            </CardContent>
          </Card>
        </Grid>

        {/* Quick Actions */}
        <Grid item xs={12}>
          <Card>
            <CardContent>
              <Typography variant="h6" gutterBottom>
                Quick Start Guide
              </Typography>
              <Alert severity="info" sx={{ mb: 2 }}>
                New to the system? Follow these steps to get started:
              </Alert>
              <Box sx={{ pl: 2 }}>
                <Typography variant="body2" paragraph>
                  <strong>1. Configure Data Sources:</strong> Go to "Data Sources" and add
                  connections to Yahoo Finance, FRED, or other data providers.
                </Typography>
                <Typography variant="body2" paragraph>
                  <strong>2. Add Assets:</strong> Navigate to "Assets" and select which stocks,
                  bonds, or other assets you want to monitor for liquidity risk.
                </Typography>
                <Typography variant="body2" paragraph>
                  <strong>3. Collect Data:</strong> Go to "Jobs" and start a data collection job
                  to download the latest market data.
                </Typography>
                <Typography variant="body2" paragraph>
                  <strong>4. Train Model:</strong> Once data is collected, start a training job
                  to teach the AI model to predict liquidity risk.
                </Typography>
                <Typography variant="body2">
                  <strong>5. View Results:</strong> After training, run predictions to see
                  liquidity risk forecasts for the next 7 days.
                </Typography>
              </Box>
            </CardContent>
          </Card>
        </Grid>

        {/* Recent Jobs */}
        {jobs && jobs.length > 0 && (
          <Grid item xs={12}>
            <Card>
              <CardContent>
                <Typography variant="h6" gutterBottom>
                  Recent Jobs
                </Typography>
                <Box>
                  {jobs.slice(0, 5).map((job) => (
                    <Box
                      key={job.id}
                      sx={{
                        display: 'flex',
                        justifyContent: 'space-between',
                        alignItems: 'center',
                        py: 1,
                        borderBottom: '1px solid #eee',
                      }}
                    >
                      <Box>
                        <Typography variant="body2">
                          {job.job_type.replace('_', ' ').toUpperCase()}
                        </Typography>
                        <Typography variant="caption" color="text.secondary">
                          {new Date(job.created_at).toLocaleString()}
                        </Typography>
                      </Box>
                      <Chip
                        label={job.status}
                        size="small"
                        color={
                          job.status === 'completed' ? 'success' :
                          job.status === 'failed' ? 'error' :
                          job.status === 'running' ? 'primary' : 'default'
                        }
                      />
                    </Box>
                  ))}
                </Box>
              </CardContent>
            </Card>
          </Grid>
        )}
      </Grid>
    </Box>
  )
}

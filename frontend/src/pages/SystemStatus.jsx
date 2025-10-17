import { useQuery } from 'react-query'
import {
  Box,
  Card,
  CardContent,
  Typography,
  Grid,
  LinearProgress,
  Chip,
  Alert,
  CircularProgress,
  List,
  ListItem,
  ListItemText,
} from '@mui/material'
import {
  CheckCircle as CheckIcon,
  Warning as WarningIcon,
  Error as ErrorIcon,
  Info as InfoIcon,
} from '@mui/icons-material'
import { api } from '../api/client'

export default function SystemStatus() {
  // Fetch system status with reduced refresh (60s is enough for system metrics)
  const { data: status, isLoading: statusLoading } = useQuery(
    'systemStatus',
    () => api.system.status().then(res => res.data),
    { refetchInterval: 60000 } // Refresh every 60 seconds
  )

  // Fetch recommendations
  const { data: recommendations, isLoading: recsLoading } = useQuery(
    'systemRecommendations',
    () => api.system.recommendations().then(res => res.data)
  )

  if (statusLoading || recsLoading) {
    return (
      <Box display="flex" justifyContent="center" alignItems="center" minHeight="400px">
        <CircularProgress />
      </Box>
    )
  }

  const getUsageColor = (percent) => {
    if (percent < 50) return 'success'
    if (percent < 80) return 'warning'
    return 'error'
  }

  const getUsageIcon = (percent) => {
    if (percent < 50) return <CheckIcon color="success" />
    if (percent < 80) return <WarningIcon color="warning" />
    return <ErrorIcon color="error" />
  }

  const getSeverityIcon = (severity) => {
    switch (severity) {
      case 'error': return <ErrorIcon color="error" />
      case 'warning': return <WarningIcon color="warning" />
      case 'info': return <InfoIcon color="info" />
      default: return <CheckIcon color="success" />
    }
  }

  return (
    <Box>
      <Typography variant="h4" gutterBottom>
        System Status
      </Typography>
      <Typography variant="body1" color="text.secondary" paragraph>
        Monitor system health, resource usage, and get optimization recommendations.
      </Typography>

      {/* Overall Status */}
      <Card sx={{ mb: 3 }}>
        <CardContent>
          <Box display="flex" alignItems="center" gap={2} mb={2}>
            <CheckIcon color="success" fontSize="large" />
            <div>
              <Typography variant="h5">System Operational</Typography>
              <Typography variant="body2" color="text.secondary">
                All services running normally
              </Typography>
            </div>
          </Box>
        </CardContent>
      </Card>

      {/* Resource Usage */}
      <Grid container spacing={3}>
        {/* CPU */}
        <Grid item xs={12} md={6}>
          <Card>
            <CardContent>
              <Box display="flex" justifyContent="space-between" alignItems="center" mb={2}>
                <Typography variant="h6">CPU Usage</Typography>
                {getUsageIcon(status?.cpu?.usage_percent || 0)}
              </Box>
              <Box display="flex" alignItems="center" gap={2} mb={1}>
                <Typography variant="h4">{status?.cpu?.usage_percent}%</Typography>
                <Typography variant="body2" color="text.secondary">
                  {status?.cpu?.cores} cores
                </Typography>
              </Box>
              <LinearProgress
                variant="determinate"
                value={status?.cpu?.usage_percent || 0}
                color={getUsageColor(status?.cpu?.usage_percent || 0)}
              />
              <Typography variant="caption" color="text.secondary" sx={{ mt: 1, display: 'block' }}>
                Current CPU utilization across all cores
              </Typography>
            </CardContent>
          </Card>
        </Grid>

        {/* Memory */}
        <Grid item xs={12} md={6}>
          <Card>
            <CardContent>
              <Box display="flex" justifyContent="space-between" alignItems="center" mb={2}>
                <Typography variant="h6">Memory (RAM)</Typography>
                {getUsageIcon(status?.memory?.usage_percent || 0)}
              </Box>
              <Box display="flex" alignItems="center" gap={2} mb={1}>
                <Typography variant="h4">{status?.memory?.usage_percent}%</Typography>
                <Typography variant="body2" color="text.secondary">
                  {status?.memory?.used_gb} / {status?.memory?.total_gb} GB
                </Typography>
              </Box>
              <LinearProgress
                variant="determinate"
                value={status?.memory?.usage_percent || 0}
                color={getUsageColor(status?.memory?.usage_percent || 0)}
              />
              <Typography variant="caption" color="text.secondary" sx={{ mt: 1, display: 'block' }}>
                System RAM usage
              </Typography>
            </CardContent>
          </Card>
        </Grid>

        {/* GPU */}
        {status?.gpu?.available && (
          <Grid item xs={12}>
            <Card>
              <CardContent>
                <Typography variant="h6" gutterBottom>
                  GPU Status
                </Typography>
                <Grid container spacing={2}>
                  {status.gpu.devices.map((gpu, idx) => (
                    <Grid item xs={12} md={6} key={idx}>
                      <Box>
                        <Box display="flex" justifyContent="space-between" alignItems="center" mb={1}>
                          <Typography variant="subtitle2">{gpu.name}</Typography>
                          {getUsageIcon(gpu.memory_percent)}
                        </Box>
                        <Box display="flex" alignItems="center" gap={2} mb={1}>
                          <Typography variant="h6">{gpu.memory_percent}%</Typography>
                          <Typography variant="body2" color="text.secondary">
                            {gpu.memory_reserved_gb} / {gpu.memory_total_gb} GB
                          </Typography>
                        </Box>
                        <LinearProgress
                          variant="determinate"
                          value={gpu.memory_percent}
                          color={getUsageColor(gpu.memory_percent)}
                        />
                      </Box>
                    </Grid>
                  ))}
                </Grid>
              </CardContent>
            </Card>
          </Grid>
        )}

        {!status?.gpu?.available && (
          <Grid item xs={12}>
            <Alert severity="info">
              No GPU detected. Training will use CPU, which may be slower.
              For faster training, consider using a machine with an NVIDIA GPU.
            </Alert>
          </Grid>
        )}

        {/* Disk */}
        <Grid item xs={12} md={6}>
          <Card>
            <CardContent>
              <Box display="flex" justifyContent="space-between" alignItems="center" mb={2}>
                <Typography variant="h6">Disk Space</Typography>
                {getUsageIcon(status?.disk?.usage_percent || 0)}
              </Box>
              <Box display="flex" alignItems="center" gap={2} mb={1}>
                <Typography variant="h4">{status?.disk?.usage_percent}%</Typography>
                <Typography variant="body2" color="text.secondary">
                  {status?.disk?.used_gb} / {status?.disk?.total_gb} GB
                </Typography>
              </Box>
              <LinearProgress
                variant="determinate"
                value={status?.disk?.usage_percent || 0}
                color={getUsageColor(status?.disk?.usage_percent || 0)}
              />
              <Typography variant="caption" color="text.secondary" sx={{ mt: 1, display: 'block' }}>
                Available disk space
              </Typography>
            </CardContent>
          </Card>
        </Grid>
      </Grid>

      {/* Recommendations */}
      {recommendations && recommendations.recommendations && recommendations.recommendations.length > 0 && (
        <Card sx={{ mt: 3 }}>
          <CardContent>
            <Typography variant="h6" gutterBottom>
              Optimization Recommendations
            </Typography>
            <Typography variant="body2" color="text.secondary" paragraph>
              Based on your system resources ({recommendations.system_resources.ram_gb} GB RAM
              {recommendations.system_resources.gpu_memory_gb && `, ${recommendations.system_resources.gpu_memory_gb} GB GPU`}),
              here are our suggestions:
            </Typography>
            <List>
              {recommendations.recommendations.map((rec, idx) => (
                <ListItem key={idx} sx={{ alignItems: 'flex-start' }}>
                  <Box sx={{ mr: 2, mt: 0.5 }}>{getSeverityIcon(rec.severity)}</Box>
                  <ListItemText
                    primary={
                      <Box display="flex" alignItems="center" gap={1}>
                        <Typography variant="subtitle2">{rec.category.toUpperCase()}</Typography>
                        <Chip
                          label={rec.severity}
                          size="small"
                          color={rec.severity === 'warning' ? 'warning' : 'info'}
                        />
                      </Box>
                    }
                    secondary={
                      <>
                        <Typography variant="body2" paragraph>
                          {rec.message}
                        </Typography>
                        {rec.suggested_config && (
                          <Box sx={{ mt: 1, p: 1, bgcolor: 'action.hover', borderRadius: 1 }}>
                            <Typography variant="caption" fontWeight="bold">
                              Suggested Configuration:
                            </Typography>
                            <pre style={{ margin: '4px 0 0 0', fontSize: '11px' }}>
                              {JSON.stringify(rec.suggested_config, null, 2)}
                            </pre>
                          </Box>
                        )}
                      </>
                    }
                  />
                </ListItem>
              ))}
            </List>
            <Alert severity="info" sx={{ mt: 2 }}>
              You can apply these recommendations in the Configuration page.
              Go to Configuration → Model Parameters or Training to adjust settings.
            </Alert>
          </CardContent>
        </Card>
      )}

      {/* System Info */}
      <Card sx={{ mt: 3 }}>
        <CardContent>
          <Typography variant="h6" gutterBottom>
            System Information
          </Typography>
          <Grid container spacing={2}>
            <Grid item xs={6} md={3}>
              <Typography variant="body2" color="text.secondary">Platform</Typography>
              <Typography variant="body1">Docker Container</Typography>
            </Grid>
            <Grid item xs={6} md={3}>
              <Typography variant="body2" color="text.secondary">CPU Cores</Typography>
              <Typography variant="body1">{status?.cpu?.cores}</Typography>
            </Grid>
            <Grid item xs={6} md={3}>
              <Typography variant="body2" color="text.secondary">Total RAM</Typography>
              <Typography variant="body1">{status?.memory?.total_gb} GB</Typography>
            </Grid>
            <Grid item xs={6} md={3}>
              <Typography variant="body2" color="text.secondary">Total Disk</Typography>
              <Typography variant="body1">{status?.disk?.total_gb} GB</Typography>
            </Grid>
            {status?.gpu?.available && (
              <>
                <Grid item xs={6} md={3}>
                  <Typography variant="body2" color="text.secondary">GPU Count</Typography>
                  <Typography variant="body1">{status.gpu.count}</Typography>
                </Grid>
                <Grid item xs={6} md={3}>
                  <Typography variant="body2" color="text.secondary">GPU Memory</Typography>
                  <Typography variant="body1">
                    {status.gpu.devices[0]?.memory_total_gb} GB
                  </Typography>
                </Grid>
              </>
            )}
          </Grid>
        </CardContent>
      </Card>
    </Box>
  )
}

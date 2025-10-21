import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from 'react-query'
import {
  Box,
  Button,
  Card,
  CardContent,
  Typography,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  Chip,
  IconButton,
  Dialog,
  DialogTitle,
  DialogContent,
  DialogActions,
  TextField,
  Select,
  MenuItem,
  FormControl,
  InputLabel,
  Alert,
  CircularProgress,
  LinearProgress,
  Collapse,
} from '@mui/material'
import {
  PlayArrow as PlayIcon,
  Stop as StopIcon,
  Refresh as RefreshIcon,
  ExpandMore as ExpandIcon,
  ExpandLess as CollapseIcon,
} from '@mui/icons-material'
import { api } from '../api/client'
import { formatDistanceToNow } from 'date-fns'

export default function Jobs() {
  const queryClient = useQueryClient()
  const [startDialogOpen, setStartDialogOpen] = useState(false)
  const [expandedJob, setExpandedJob] = useState(null)
  const [newJob, setNewJob] = useState({
    job_type: 'data_collection',
    parameters: {}
  })
  const [filters, setFilters] = useState({
    job_type: '',
    status: ''
  })

  // Fetch jobs with smart auto-refresh (only when jobs are running)
  const { data: jobs, isLoading } = useQuery(
    ['jobs', filters],
    () => api.jobs.list(filters).then(res => res.data),
    {
      // Smart refetch: 2s when jobs running, 30s when idle
      refetchInterval: (data) => {
        if (!data || data.length === 0) return 30000
        const hasRunning = data.some(job => job.status === 'running' || job.status === 'pending')
        return hasRunning ? 2000 : 30000
      }
    }
  )

  // Create job mutation
  const createJobMutation = useMutation(
    (data) => api.jobs.create(data),
    {
      onSuccess: () => {
        queryClient.invalidateQueries('jobs')
        setStartDialogOpen(false)
        setNewJob({ job_type: 'data_collection', parameters: {} })
      }
    }
  )

  // Cancel job mutation
  const cancelJobMutation = useMutation(
    (id) => api.jobs.cancel(id),
    {
      onSuccess: () => {
        queryClient.invalidateQueries('jobs')
      }
    }
  )

  const handleStartJob = () => {
    createJobMutation.mutate(newJob)
  }

  const [cancelDialogOpen, setCancelDialogOpen] = useState(false);
  const [jobToCancel, setJobToCancel] = useState(null);

  const handleCancelJob = (id) => {
    setJobToCancel(id);
    setCancelDialogOpen(true);
  };

  const confirmCancelJob = () => {
    if (jobToCancel) {
      cancelJobMutation.mutate(jobToCancel);
    }
    setCancelDialogOpen(false);
    setJobToCancel(null);
  };

  const getStatusColor = (status) => {
    switch (status) {
      case 'completed': return 'success'
      case 'failed': return 'error'
      case 'running': return 'primary'
      case 'pending': return 'warning'
      default: return 'default'
    }
  }

  const getJobTypeLabel = (type) => {
    const labels = {
      data_collection: 'Data Collection',
      training: 'Model Training',
      prediction: 'Prediction',
      backtest: 'Backtest'
    }
    return labels[type] || type
  }

  const getExecutionTime = (job) => {
    if (!job.started_at) return '-'
    if (!job.completed_at) {
      return `${formatDistanceToNow(new Date(job.started_at))} (running)`
    }
    return job.execution_time_seconds ? `${Math.round(job.execution_time_seconds)}s` : '-'
  }

  if (isLoading) {
    return (
      <Box display="flex" justifyContent="center" alignItems="center" minHeight="400px">
        <CircularProgress />
      </Box>
    )
  }

  const runningJobs = jobs?.filter(j => j.status === 'running') || []

  return (
    <Box>
      <Box display="flex" justifyContent="space-between" alignItems="center" mb={3}>
        <div>
          <Typography variant="h4" gutterBottom>
            Background Jobs
          </Typography>
          <Typography variant="body1" color="text.secondary">
            Monitor and manage data collection, training, and prediction tasks.
          </Typography>
        </div>
        <Button
          variant="contained"
          startIcon={<PlayIcon />}
          onClick={() => setStartDialogOpen(true)}
        >
          Start New Job
        </Button>
      </Box>

      <Alert severity="info" sx={{ mb: 3 }}>
        <strong>Job Types:</strong>
        <br />
        • <strong>Data Collection:</strong> Downloads latest market data from configured sources
        <br />
        • <strong>Training:</strong> Trains the AI model on collected data (may take 10-30 minutes)
        <br />
        • <strong>Prediction:</strong> Generates liquidity risk forecasts for next 7 days
        <br />
        • <strong>Backtest:</strong> Tests model accuracy on historical data
      </Alert>

      {/* Running Jobs */}
      {runningJobs.length > 0 && (
        <Card sx={{ mb: 2 }}>
          <CardContent>
            <Typography variant="h6" gutterBottom>
              Currently Running ({runningJobs.length})
            </Typography>
            {runningJobs.map(job => (
              <Box key={job.id} sx={{ mb: 2 }}>
                <Box display="flex" justifyContent="space-between" alignItems="center" mb={1}>
                  <Typography variant="body2">
                    {getJobTypeLabel(job.job_type)} (Job #{job.id})
                  </Typography>
                  <IconButton size="small" color="error" onClick={() => handleCancelJob(job.id)}>
                    <StopIcon />
                  </IconButton>
                </Box>
                <LinearProgress variant="determinate" value={job.progress} />
                <Box display="flex" justifyContent="space-between" alignItems="center" mt={0.5}>
                  <Typography variant="caption" color="text.secondary">
                    {Math.round(job.progress)}% complete
                  </Typography>
                  {job.current_step && (
                    <Typography variant="caption" color="primary" fontStyle="italic">
                      {job.current_step}
                    </Typography>
                  )}
                </Box>
              </Box>
            ))}
          </CardContent>
        </Card>
      )}

      {/* Filters */}
      <Card sx={{ mb: 2 }}>
        <CardContent>
          <Box display="flex" alignItems="center" gap={2}>
            <FormControl size="small" sx={{ minWidth: 200 }}>
              <InputLabel>Job Type</InputLabel>
              <Select
                value={filters.job_type}
                label="Job Type"
                onChange={(e) => setFilters({ ...filters, job_type: e.target.value })}
              >
                <MenuItem value="">All Types</MenuItem>
                <MenuItem value="data_collection">Data Collection</MenuItem>
                <MenuItem value="training">Training</MenuItem>
                <MenuItem value="prediction">Prediction</MenuItem>
                <MenuItem value="backtest">Backtest</MenuItem>
              </Select>
            </FormControl>
            <FormControl size="small" sx={{ minWidth: 150 }}>
              <InputLabel>Status</InputLabel>
              <Select
                value={filters.status}
                label="Status"
                onChange={(e) => setFilters({ ...filters, status: e.target.value })}
              >
                <MenuItem value="">All Statuses</MenuItem>
                <MenuItem value="running">Running</MenuItem>
                <MenuItem value="completed">Completed</MenuItem>
                <MenuItem value="failed">Failed</MenuItem>
                <MenuItem value="pending">Pending</MenuItem>
              </Select>
            </FormControl>
            <Button
              startIcon={<RefreshIcon />}
              onClick={() => queryClient.invalidateQueries('jobs')}
            >
              Refresh
            </Button>
          </Box>
        </CardContent>
      </Card>

      {/* Jobs Table */}
      <Card>
        <CardContent>
          <TableContainer>
            <Table>
              <TableHead>
                <TableRow>
                  <TableCell>ID</TableCell>
                  <TableCell>Type</TableCell>
                  <TableCell>Status</TableCell>
                  <TableCell>Progress</TableCell>
                  <TableCell>Started</TableCell>
                  <TableCell>Duration</TableCell>
                  <TableCell>Memory</TableCell>
                  <TableCell align="right">Actions</TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {jobs && jobs.length > 0 ? (
                  jobs.map((job) => (
                    <>
                      <TableRow key={job.id}>
                        <TableCell>{job.id}</TableCell>
                        <TableCell>{getJobTypeLabel(job.job_type)}</TableCell>
                        <TableCell>
                          <Chip
                            label={job.status}
                            color={getStatusColor(job.status)}
                            size="small"
                          />
                        </TableCell>
                        <TableCell>
                          {job.status === 'running' ? `${Math.round(job.progress)}%` : '-'}
                        </TableCell>
                        <TableCell>
                          {job.started_at
                            ? formatDistanceToNow(new Date(job.started_at), { addSuffix: true })
                            : 'Not started'}
                        </TableCell>
                        <TableCell>{getExecutionTime(job)}</TableCell>
                        <TableCell>
                          {job.peak_memory_mb ? `${Math.round(job.peak_memory_mb)} MB` : '-'}
                        </TableCell>
                        <TableCell align="right">
                          <IconButton
                            size="small"
                            onClick={() => setExpandedJob(expandedJob === job.id ? null : job.id)}
                          >
                            {expandedJob === job.id ? <CollapseIcon /> : <ExpandIcon />}
                          </IconButton>
                          {job.status === 'running' && (
                            <IconButton
                              size="small"
                              color="error"
                              onClick={() => handleCancelJob(job.id)}
                            >
                              <StopIcon />
                            </IconButton>
                          )}
                        </TableCell>
                      </TableRow>
                      <TableRow>
                        <TableCell colSpan={8} sx={{ py: 0 }}>
                          <Collapse in={expandedJob === job.id}>
                            <Box sx={{ py: 2 }}>
                              <Typography variant="subtitle2" gutterBottom>
                                Job Details
                              </Typography>
                              <Box sx={{ pl: 2 }}>
                                <Typography variant="body2">
                                  <strong>Created:</strong> {new Date(job.created_at).toLocaleString()}
                                </Typography>
                                {job.started_at && (
                                  <Typography variant="body2">
                                    <strong>Started:</strong> {new Date(job.started_at).toLocaleString()}
                                  </Typography>
                                )}
                                {job.completed_at && (
                                  <Typography variant="body2">
                                    <strong>Completed:</strong> {new Date(job.completed_at).toLocaleString()}
                                  </Typography>
                                )}
                                {job.parameters && Object.keys(job.parameters).length > 0 && (
                                  <Typography variant="body2">
                                    <strong>Parameters:</strong> {JSON.stringify(job.parameters)}
                                  </Typography>
                                )}
                                {job.result && (
                                  <Box sx={{ mt: 1 }}>
                                    <Typography variant="subtitle2">Results:</Typography>
                                    <pre style={{ fontSize: '12px', background: '#f5f5f5', padding: '8px', borderRadius: '4px' }}>
                                      {JSON.stringify(job.result, null, 2)}
                                    </pre>
                                  </Box>
                                )}
                                {job.error_message && (
                                  <Alert severity="error" sx={{ mt: 1 }}>
                                    <Typography variant="subtitle2">Error:</Typography>
                                    <Typography variant="body2">
                                      {job.user_friendly_error || job.error_message}
                                    </Typography>
                                  </Alert>
                                )}
                              </Box>
                            </Box>
                          </Collapse>
                        </TableCell>
                      </TableRow>
                    </>
                  ))
                ) : (
                  <TableRow>
                    <TableCell colSpan={8} align="center">
                      <Typography color="text.secondary">
                        No jobs yet. Click "Start New Job" to begin.
                      </Typography>
                    </TableCell>
                  </TableRow>
                )}
              </TableBody>
            </Table>
          </TableContainer>
        </CardContent>
      </Card>

      {/* Cancel Job Dialog */}
      <Dialog open={cancelDialogOpen} onClose={() => setCancelDialogOpen(false)}>
        <DialogTitle>Cancel Job</DialogTitle>
        <DialogContent>
          <Typography>Are you sure you want to cancel job #{jobToCancel}?</Typography>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setCancelDialogOpen(false)}>Back</Button>
          <Button onClick={confirmCancelJob} color="error">Cancel Job</Button>
        </DialogActions>
      </Dialog>

      {/* Start Job Dialog */}
      <Dialog open={startDialogOpen} onClose={() => setStartDialogOpen(false)} maxWidth="sm" fullWidth>
        <DialogTitle>Start New Job</DialogTitle>
        <DialogContent>
          <Box sx={{ pt: 2, display: 'flex', flexDirection: 'column', gap: 2 }}>
            <FormControl fullWidth>
              <InputLabel>Job Type</InputLabel>
              <Select
                value={newJob.job_type}
                label="Job Type"
                onChange={(e) => setNewJob({ ...newJob, job_type: e.target.value })}
              >
                <MenuItem value="data_collection">Data Collection</MenuItem>
                <MenuItem value="training">Model Training</MenuItem>
                <MenuItem value="prediction">Generate Predictions</MenuItem>
                <MenuItem value="backtest">Run Backtest</MenuItem>
              </Select>
            </FormControl>

            <Alert severity="info">
              {newJob.job_type === 'data_collection' && (
                'Downloads the latest market data from all enabled data sources. Takes 1-5 minutes depending on number of assets.'
              )}
              {newJob.job_type === 'training' && (
                'Trains the AI model on collected data. This may take 10-30 minutes depending on your hardware.'
              )}
              {newJob.job_type === 'prediction' && (
                'Generates liquidity risk predictions for the next 7 days. Requires a trained model.'
              )}
              {newJob.job_type === 'backtest' && (
                'Tests model performance on historical data. Takes 20-60 minutes for comprehensive testing.'
              )}
            </Alert>

  const { data: completedDataJobs } = useQuery(
    'completedDataJobs',
    () => api.jobs.list({ job_type: 'data_collection', status: 'completed' }).then(res => res.data),
    {
      enabled: startDialogOpen && newJob.job_type === 'training',
    }
  );

            {newJob.job_type === 'training' && (
              <>
                <FormControl fullWidth>
                  <InputLabel>Data Source Job</InputLabel>
                  <Select
                    value={newJob.parameters.data_job_id || ''}
                    label="Data Source Job"
                    onChange={(e) => setNewJob({
                      ...newJob,
                      parameters: { ...newJob.parameters, data_job_id: e.target.value }
                    })}
                  >
                    {completedDataJobs && completedDataJobs.map(job => (
                      <MenuItem key={job.id} value={job.id}>
                        Job #{job.id} - {new Date(job.completed_at).toLocaleString()}
                      </MenuItem>
                    ))}
                  </Select>
                </FormControl>
                <TextField
                  label="Training Start Date"
                  type="date"
                  fullWidth
                  InputLabelProps={{ shrink: true }}
                  defaultValue="2019-01-01"
                  onChange={(e) => setNewJob({
                    ...newJob,
                    parameters: { ...newJob.parameters, train_start: e.target.value }
                  })}
                />
                <TextField
                  label="Training End Date"
                  type="date"
                  fullWidth
                  InputLabelProps={{ shrink: true }}
                  defaultValue="2023-12-31"
                  onChange={(e) => setNewJob({
                    ...newJob,
                    parameters: { ...newJob.parameters, train_end: e.target.value }
                  })}
                />
              </>
            )}
          </Box>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setStartDialogOpen(false)}>Cancel</Button>
          <Button
            variant="contained"
            onClick={handleStartJob}
            disabled={createJobMutation.isLoading}
          >
            Start Job
          </Button>
        </DialogActions>
      </Dialog>
    </Box>
  )
}

import { useState } from 'react'
import { useQuery } from 'react-query'
import {
  Box,
  Container,
  Typography,
  Card,
  CardContent,
  Grid,
  Paper,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  Chip,
  CircularProgress,
  Alert,
  Tabs,
  Tab,
  LinearProgress,
  IconButton,
  Tooltip,
  Divider
} from '@mui/material'
import {
  Assessment as AssessmentIcon,
  TrendingUp as TrendingUpIcon,
  Warning as WarningIcon,
  CheckCircle as CheckCircleIcon,
  Error as ErrorIcon,
  Refresh as RefreshIcon,
  Timeline as TimelineIcon,
  Dashboard as DashboardIcon,
  Description as DescriptionIcon
} from '@mui/icons-material'
import { api } from '../api/client'

function TabPanel({ children, value, index, ...other }) {
  return (
    <div role="tabpanel" hidden={value !== index} {...other}>
      {value === index && <Box sx={{ py: 3 }}>{children}</Box>}
    </div>
  )
}

function RiskGauge({ value, label }) {
  const getRiskColor = (score) => {
    if (score >= 75) return 'error'
    if (score >= 50) return 'warning'
    if (score >= 25) return 'info'
    return 'success'
  }

  const getRiskLevel = (score) => {
    if (score >= 75) return 'CRITICAL'
    if (score >= 50) return 'HIGH'
    if (score >= 25) return 'MEDIUM'
    return 'LOW'
  }

  return (
    <Box sx={{ textAlign: 'center' }}>
      <Box sx={{ position: 'relative', display: 'inline-flex', mb: 2 }}>
        <CircularProgress
          variant="determinate"
          value={value}
          size={120}
          thickness={4}
          color={getRiskColor(value)}
        />
        <Box
          sx={{
            top: 0,
            left: 0,
            bottom: 0,
            right: 0,
            position: 'absolute',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            flexDirection: 'column'
          }}
        >
          <Typography variant="h4" component="div" color="text.primary">
            {value.toFixed(0)}
          </Typography>
          <Typography variant="caption" color="text.secondary">
            / 100
          </Typography>
        </Box>
      </Box>
      <Typography variant="body2" color="text.secondary" gutterBottom>
        {label}
      </Typography>
      <Chip
        label={getRiskLevel(value)}
        color={getRiskColor(value)}
        size="small"
        sx={{ fontWeight: 'bold' }}
      />
    </Box>
  )
}

export default function Results() {
  const [selectedTab, setSelectedTab] = useState(0)
  const [selectedJobId, setSelectedJobId] = useState(null)

  const { data: resultsList, isLoading: loadingList, refetch } = useQuery({
    queryKey: ['results-list'],
    queryFn: async () => {
      const response = await api.results.list({ status: 'completed' })
      return response.data
    }
  })

  const { data: selectedResult, isLoading: loadingResult } = useQuery({
    queryKey: ['result-detail', selectedJobId],
    queryFn: async () => {
      const response = await api.results.get(selectedJobId)
      return response.data
    },
    enabled: !!selectedJobId
  })

  const { data: executiveSummary } = useQuery({
    queryKey: ['executive-summary', selectedJobId],
    queryFn: async () => {
      const response = await api.results.executiveSummary(selectedJobId)
      return response.data
    },
    enabled: !!selectedJobId
  })

  const { data: dataQuality } = useQuery({
    queryKey: ['data-quality', selectedJobId],
    queryFn: async () => {
      const response = await api.results.dataQuality(selectedJobId)
      return response.data
    },
    enabled: !!selectedJobId && selectedResult?.job_type === 'data_collection'
  })

  const { data: riskScores } = useQuery({
    queryKey: ['risk-scores', selectedJobId],
    queryFn: async () => {
      const response = await api.results.riskScores(selectedJobId)
      return response.data
    },
    enabled: !!selectedJobId && ['prediction', 'backtest', 'training'].includes(selectedResult?.job_type)
  })

  const formatDate = (dateString) => {
    if (!dateString) return 'N/A'
    return new Date(dateString).toLocaleString()
  }

  const getJobTypeIcon = (type) => {
    switch (type) {
      case 'data_collection':
        return <DashboardIcon />
      case 'training':
        return <TimelineIcon />
      case 'prediction':
        return <TrendingUpIcon />
      case 'backtest':
        return <AssessmentIcon />
      default:
        return <DescriptionIcon />
    }
  }

  const getJobTypeColor = (type) => {
    switch (type) {
      case 'data_collection':
        return 'primary'
      case 'training':
        return 'secondary'
      case 'prediction':
        return 'success'
      case 'backtest':
        return 'info'
      default:
        return 'default'
    }
  }

  if (loadingList) {
    return (
      <Container maxWidth="xl" sx={{ mt: 4, mb: 4 }}>
        <Box sx={{ display: 'flex', justifyContent: 'center', alignItems: 'center', minHeight: '400px' }}>
          <CircularProgress />
        </Box>
      </Container>
    )
  }

  return (
    <Container maxWidth="xl" sx={{ mt: 4, mb: 4 }}>
      <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 3 }}>
        <Box>
          <Typography variant="h4" gutterBottom sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
            <AssessmentIcon fontSize="large" />
            Results & Reports
          </Typography>
          <Typography variant="body2" color="text.secondary">
            View comprehensive analysis results and data quality reports
          </Typography>
        </Box>
        <IconButton onClick={() => refetch()} color="primary">
          <RefreshIcon />
        </IconButton>
      </Box>

      <Grid container spacing={3}>
        {/* Results List */}
        <Grid item xs={12} md={4}>
          <Card>
            <CardContent>
              <Typography variant="h6" gutterBottom>
                Available Results ({resultsList?.total || 0})
              </Typography>
              <Divider sx={{ my: 2 }} />
              {resultsList?.results?.length === 0 ? (
                <Alert severity="info">No completed jobs with results yet</Alert>
              ) : (
                <TableContainer sx={{ maxHeight: 600 }}>
                  <Table size="small" stickyHeader>
                    <TableHead>
                      <TableRow>
                        <TableCell>Job</TableCell>
                        <TableCell>Type</TableCell>
                        <TableCell>Completed</TableCell>
                      </TableRow>
                    </TableHead>
                    <TableBody>
                      {resultsList?.results?.map((result) => (
                        <TableRow
                          key={result.job_id}
                          hover
                          selected={selectedJobId === result.job_id}
                          onClick={() => setSelectedJobId(result.job_id)}
                          sx={{ cursor: 'pointer' }}
                        >
                          <TableCell>#{result.job_id}</TableCell>
                          <TableCell>
                            <Chip
                              icon={getJobTypeIcon(result.job_type)}
                              label={result.job_type}
                              size="small"
                              color={getJobTypeColor(result.job_type)}
                            />
                          </TableCell>
                          <TableCell sx={{ fontSize: '0.75rem' }}>
                            {formatDate(result.completed_at)}
                          </TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </TableContainer>
              )}
            </CardContent>
          </Card>
        </Grid>

        {/* Result Details */}
        <Grid item xs={12} md={8}>
          {!selectedJobId ? (
            <Card>
              <CardContent sx={{ textAlign: 'center', py: 8 }}>
                <AssessmentIcon sx={{ fontSize: 64, color: 'text.secondary', mb: 2 }} />
                <Typography variant="h6" color="text.secondary">
                  Select a result to view details
                </Typography>
              </CardContent>
            </Card>
          ) : loadingResult ? (
            <Card>
              <CardContent sx={{ textAlign: 'center', py: 8 }}>
                <CircularProgress />
              </CardContent>
            </Card>
          ) : (
            <Box>
              <Card sx={{ mb: 3 }}>
                <CardContent>
                  <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 2 }}>
                    <Typography variant="h5">
                      Job #{selectedResult?.job_id} - {selectedResult?.job_type}
                    </Typography>
                    <Chip label={selectedResult?.status} color="success" />
                  </Box>
                  <Grid container spacing={2}>
                    <Grid item xs={6} sm={3}>
                      <Typography variant="body2" color="text.secondary">Created</Typography>
                      <Typography variant="body1">{formatDate(selectedResult?.created_at)}</Typography>
                    </Grid>
                    <Grid item xs={6} sm={3}>
                      <Typography variant="body2" color="text.secondary">Completed</Typography>
                      <Typography variant="body1">{formatDate(selectedResult?.completed_at)}</Typography>
                    </Grid>
                    <Grid item xs={6} sm={3}>
                      <Typography variant="body2" color="text.secondary">Execution Time</Typography>
                      <Typography variant="body1">
                        {selectedResult?.execution_time_seconds?.toFixed(2) || 'N/A'}s
                      </Typography>
                    </Grid>
                    <Grid item xs={6} sm={3}>
                      <Typography variant="body2" color="text.secondary">Peak Memory</Typography>
                      <Typography variant="body1">
                        {selectedResult?.peak_memory_mb?.toFixed(0) || 'N/A'} MB
                      </Typography>
                    </Grid>
                  </Grid>
                </CardContent>
              </Card>

              <Tabs value={selectedTab} onChange={(e, v) => setSelectedTab(v)} sx={{ mb: 2 }}>
                <Tab label="Executive Summary" />
                {selectedResult?.job_type === 'data_collection' && <Tab label="Data Quality" />}
                {['prediction', 'backtest', 'training'].includes(selectedResult?.job_type) && <Tab label="Risk Scores" />}
                <Tab label="Raw Result" />
              </Tabs>

              <TabPanel value={selectedTab} index={0}>
                <Card>
                  <CardContent>
                    <Typography variant="h6" gutterBottom>
                      {executiveSummary?.title || 'Executive Summary'}
                    </Typography>
                    <Divider sx={{ my: 2 }} />
                    {executiveSummary ? (
                      <Box>
                        <Typography variant="body1" paragraph>
                          {executiveSummary.message || 'Summary not available'}
                        </Typography>
                        {executiveSummary.key_metrics && (
                          <Grid container spacing={2} sx={{ mt: 2 }}>
                            {Object.entries(executiveSummary.key_metrics).map(([key, value]) => (
                              <Grid item xs={6} sm={4} key={key}>
                                <Paper sx={{ p: 2, textAlign: 'center' }}>
                                  <Typography variant="body2" color="text.secondary">
                                    {key.replace(/_/g, ' ').toUpperCase()}
                                  </Typography>
                                  <Typography variant="h6">
                                    {typeof value === 'boolean' ? (value ? 'Yes' : 'No') : value}
                                  </Typography>
                                </Paper>
                              </Grid>
                            ))}
                          </Grid>
                        )}
                      </Box>
                    ) : (
                      <Alert severity="info">Executive summary not available</Alert>
                    )}
                  </CardContent>
                </Card>
              </TabPanel>

              {selectedResult?.job_type === 'data_collection' && (
                <TabPanel value={selectedTab} index={1}>
                  <Card>
                    <CardContent>
                      <Typography variant="h6" gutterBottom>Data Quality Report</Typography>
                      <Divider sx={{ my: 2 }} />
                      {dataQuality ? (
                        <Grid container spacing={3}>
                          <Grid item xs={12} sm={6} md={3}>
                            <RiskGauge value={dataQuality.quality_score || 0} label="Overall Quality Score" />
                          </Grid>
                          <Grid item xs={12} sm={6} md={3}>
                            <RiskGauge value={dataQuality.completeness || 0} label="Completeness" />
                          </Grid>
                          <Grid item xs={12} sm={6} md={3}>
                            <Box sx={{ textAlign: 'center' }}>
                              {dataQuality.fit_for_engine ? (
                                <CheckCircleIcon sx={{ fontSize: 80, color: 'success.main', mb: 2 }} />
                              ) : (
                                <ErrorIcon sx={{ fontSize: 80, color: 'error.main', mb: 2 }} />
                              )}
                              <Typography variant="body2" color="text.secondary" gutterBottom>
                                Fit for Engine
                              </Typography>
                              <Chip
                                label={dataQuality.fit_for_engine ? 'YES' : 'NO'}
                                color={dataQuality.fit_for_engine ? 'success' : 'error'}
                                sx={{ fontWeight: 'bold' }}
                              />
                            </Box>
                          </Grid>
                          <Grid item xs={12} sm={6} md={3}>
                            <Box sx={{ textAlign: 'center' }}>
                              <Typography variant="h3" color="warning.main">
                                {dataQuality.anomalies_detected || 0}
                              </Typography>
                              <Typography variant="body2" color="text.secondary" gutterBottom>
                                Anomalies Detected
                              </Typography>
                              <Typography variant="body2" color="success.main">
                                {dataQuality.anomalies_fixed || 0} Fixed
                              </Typography>
                            </Box>
                          </Grid>
                        </Grid>
                      ) : (
                        <Alert severity="info">Data quality report not available</Alert>
                      )}
                    </CardContent>
                  </Card>
                </TabPanel>
              )}

              {['prediction', 'backtest', 'training'].includes(selectedResult?.job_type) && (
                <TabPanel value={selectedTab} index={selectedResult?.job_type === 'data_collection' ? 2 : 1}>
                  <Card>
                    <CardContent>
                      <Typography variant="h6" gutterBottom>Risk Scores</Typography>
                      <Divider sx={{ my: 2 }} />
                      {riskScores?.risk_scores ? (
                        <Grid container spacing={3}>
                          <Grid item xs={12} sm={6} md={3}>
                            <RiskGauge
                              value={riskScores.risk_scores.overall_risk_score || 0}
                              label="Overall Risk"
                            />
                          </Grid>
                          <Grid item xs={12} sm={6} md={3}>
                            <RiskGauge
                              value={riskScores.risk_scores.market_liquidity || 0}
                              label="Market Liquidity"
                            />
                          </Grid>
                          <Grid item xs={12} sm={6} md={3}>
                            <RiskGauge
                              value={riskScores.risk_scores.funding_liquidity || 0}
                              label="Funding Liquidity"
                            />
                          </Grid>
                          <Grid item xs={12} sm={6} md={3}>
                            <RiskGauge
                              value={riskScores.risk_scores.systemic_risk || 0}
                              label="Systemic Risk"
                            />
                          </Grid>
                        </Grid>
                      ) : (
                        <Alert severity="info">Risk scores not available</Alert>
                      )}
                    </CardContent>
                  </Card>
                </TabPanel>
              )}

              <TabPanel value={selectedTab} index={selectedResult?.job_type === 'data_collection' ? 2 : (['prediction', 'backtest', 'training'].includes(selectedResult?.job_type) ? 2 : 1)}>
                <Card>
                  <CardContent>
                    <Typography variant="h6" gutterBottom>Raw Result Data</Typography>
                    <Divider sx={{ my: 2 }} />
                    <Paper sx={{ p: 2, bgcolor: 'grey.100', overflow: 'auto', maxHeight: 400 }}>
                      <pre style={{ margin: 0, fontSize: '0.875rem' }}>
                        {JSON.stringify(selectedResult?.result, null, 2)}
                      </pre>
                    </Paper>
                  </CardContent>
                </Card>
              </TabPanel>
            </Box>
          )}
        </Grid>
      </Grid>
    </Container>
  )
}

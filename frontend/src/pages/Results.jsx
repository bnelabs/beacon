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
  Divider,
  Button,
  List,
  ListItem,
  ListItemText,
  Stack
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
  Description as DescriptionIcon,
  Download as DownloadIcon,
  AccountBalance as BankIcon,
  Lan as NetworkIcon,
  Info as InfoIcon
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

  // EU AI Act Compliant Explainability
  const { data: explanation } = useQuery({
    queryKey: ['explanation', selectedJobId],
    queryFn: async () => {
      const response = await api.explainability.explanation(selectedJobId)
      return response.data
    },
    enabled: !!selectedJobId && ['training', 'prediction'].includes(selectedResult?.job_type)
  })

  // Per-Bank Risk Analysis
  const { data: bankRisks } = useQuery({
    queryKey: ['bank-risks', selectedJobId],
    queryFn: async () => {
      const response = await api.explainability.bankRisks(selectedJobId)
      return response.data
    },
    enabled: !!selectedJobId && ['training', 'prediction'].includes(selectedResult?.job_type)
  })

  // Contagion Analysis
  const { data: contagionAnalysis } = useQuery({
    queryKey: ['contagion-analysis', selectedJobId],
    queryFn: async () => {
      const response = await api.explainability.contagionAnalysis(selectedJobId)
      return response.data
    },
    enabled: !!selectedJobId && ['training', 'prediction'].includes(selectedResult?.job_type)
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
            Results & AI Explainability
          </Typography>
          <Typography variant="body2" color="text.secondary">
            EU AI Act compliant - Full transparency, per-bank risk, and contagion analysis
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
                  Select a result to view AI explainability and analysis
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
                <Tab label="Summary" />
                {selectedResult?.job_type === 'training' && <Tab label="Training Metrics" />}
                {['training', 'prediction'].includes(selectedResult?.job_type) && <Tab label="AI Explainability" />}
                {['training', 'prediction'].includes(selectedResult?.job_type) && <Tab label="Per-Bank Risk" />}
                {['training', 'prediction'].includes(selectedResult?.job_type) && <Tab label="Contagion Analysis" />}
                {selectedResult?.job_type === 'data_collection' && <Tab label="Data Quality" />}
                <Tab label="Raw Result" />
              </Tabs>

              {/* Summary Tab */}
              <TabPanel value={selectedTab} index={0}>
                <Card>
                  <CardContent>
                    <Typography variant="h6" gutterBottom>
                      {executiveSummary?.title || 'Executive Summary'}
                    </Typography>
                    <Divider sx={{ my: 2 }} />
                    {executiveSummary ? (
                      <Box>
                        <Typography variant="body1" paragraph sx={{ whiteSpace: 'pre-line' }}>
                          {executiveSummary.message || executiveSummary.summary || 'Summary not available'}
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
                                    {typeof value === 'boolean' ? (value ? 'Yes' : 'No') :
                                     typeof value === 'number' ? value.toFixed(4) : value}
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

              {/* Training Metrics Tab */}
              {selectedResult?.job_type === 'training' && (
                <TabPanel value={selectedTab} index={1}>
                  <Grid container spacing={3}>
                    {/* Training Visualizations */}
                    <Grid item xs={12}>
                      <Card>
                        <CardContent>
                          <Typography variant="h6" gutterBottom>Training Metrics & Loss Curves</Typography>
                          <Divider sx={{ my: 2 }} />
                          <Grid container spacing={2}>
                            {['loss_curves', 'predictions_vs_actual', 'error_distribution', 'residuals', 'summary_table'].map((vizName) => (
                              <Grid item xs={12} md={6} key={vizName}>
                                <Paper sx={{ p: 2 }}>
                                  <Typography variant="subtitle2" gutterBottom>
                                    {vizName.replace(/_/g, ' ').toUpperCase()}
                                  </Typography>
                                  <Box
                                    component="img"
                                    src={api.explainability.visualization(selectedJobId, vizName)}
                                    alt={vizName}
                                    sx={{ width: '100%', height: 'auto', borderRadius: 1 }}
                                    onError={(e) => {
                                      e.target.style.display = 'none'
                                      e.target.nextSibling.style.display = 'block'
                                    }}
                                  />
                                  <Alert severity="info" sx={{ display: 'none' }}>
                                    Visualization not available
                                  </Alert>
                                </Paper>
                              </Grid>
                            ))}
                          </Grid>
                        </CardContent>
                      </Card>
                    </Grid>

                    {/* Model Performance Metrics */}
                    <Grid item xs={12}>
                      <Card>
                        <CardContent>
                          <Typography variant="h6" gutterBottom>Model Performance</Typography>
                          <Divider sx={{ my: 2 }} />
                          <Grid container spacing={2}>
                            {selectedResult?.result?.test_r2 && (
                              <Grid item xs={6} sm={3}>
                                <RiskGauge
                                  value={(selectedResult.result.test_r2 * 100)}
                                  label="R² Score (%)"
                                />
                              </Grid>
                            )}
                            {selectedResult?.result?.test_mae && (
                              <Grid item xs={6} sm={3}>
                                <Box sx={{ textAlign: 'center' }}>
                                  <Typography variant="h4" color="primary">
                                    {selectedResult.result.test_mae.toFixed(4)}
                                  </Typography>
                                  <Typography variant="body2" color="text.secondary">
                                    MAE
                                  </Typography>
                                </Box>
                              </Grid>
                            )}
                            {selectedResult?.result?.test_rmse && (
                              <Grid item xs={6} sm={3}>
                                <Box sx={{ textAlign: 'center' }}>
                                  <Typography variant="h4" color="secondary">
                                    {selectedResult.result.test_rmse.toFixed(4)}
                                  </Typography>
                                  <Typography variant="body2" color="text.secondary">
                                    RMSE
                                  </Typography>
                                </Box>
                              </Grid>
                            )}
                            {selectedResult?.result?.epochs_trained && (
                              <Grid item xs={6} sm={3}>
                                <Box sx={{ textAlign: 'center' }}>
                                  <Typography variant="h4" color="info.main">
                                    {selectedResult.result.epochs_trained}
                                  </Typography>
                                  <Typography variant="body2" color="text.secondary">
                                    Epochs
                                  </Typography>
                                </Box>
                              </Grid>
                            )}
                          </Grid>
                          <Box sx={{ mt: 2 }}>
                            <Stack direction="row" spacing={2}>
                              <Button
                                variant="outlined"
                                startIcon={<DownloadIcon />}
                                href={api.explainability.downloadPredictions(selectedJobId, 'csv')}
                                target="_blank"
                              >
                                Download CSV
                              </Button>
                              <Button
                                variant="outlined"
                                startIcon={<DownloadIcon />}
                                href={api.explainability.downloadPredictions(selectedJobId, 'excel')}
                                target="_blank"
                              >
                                Download Excel
                              </Button>
                            </Stack>
                          </Box>
                        </CardContent>
                      </Card>
                    </Grid>
                  </Grid>
                </TabPanel>
              )}

              {/* AI Explainability Tab */}
              {['training', 'prediction'].includes(selectedResult?.job_type) && (
                <TabPanel value={selectedTab} index={selectedResult?.job_type === 'training' ? 2 : 1}>
                  <Card>
                    <CardContent>
                      <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 2 }}>
                        <InfoIcon color="primary" />
                        <Typography variant="h6">
                          EU AI Act Compliant Explainability
                        </Typography>
                        <Chip label="NO BLACK BOX" color="success" size="small" />
                      </Box>
                      <Divider sx={{ my: 2 }} />
                      {explanation ? (
                        <Grid container spacing={3}>
                          <Grid item xs={12}>
                            <Alert severity="success">
                              <Typography variant="subtitle2" gutterBottom>
                                {explanation.explainability_compliance}
                              </Typography>
                              <Typography variant="body2">
                                {explanation.summary}
                              </Typography>
                            </Alert>
                          </Grid>
                          <Grid item xs={12} md={6}>
                            <Paper sx={{ p: 2 }}>
                              <Typography variant="subtitle1" gutterBottom fontWeight="bold">
                                Feature Importance
                              </Typography>
                              <List dense>
                                {Object.entries(explanation.feature_importance || {}).slice(0, 10).map(([feature, importance]) => (
                                  <ListItem key={feature}>
                                    <ListItemText
                                      primary={feature}
                                      secondary={
                                        <LinearProgress
                                          variant="determinate"
                                          value={Math.abs(importance) * 100}
                                          sx={{ mt: 1 }}
                                        />
                                      }
                                    />
                                  </ListItem>
                                ))}
                              </List>
                            </Paper>
                          </Grid>
                          <Grid item xs={12} md={6}>
                            <Paper sx={{ p: 2 }}>
                              <Typography variant="subtitle1" gutterBottom fontWeight="bold">
                                Model Compliance
                              </Typography>
                              <List dense>
                                {Object.entries(explanation.compliance || {}).map(([key, value]) => (
                                  <ListItem key={key}>
                                    <ListItemText
                                      primary={key.replace(/_/g, ' ').toUpperCase()}
                                      secondary={value}
                                    />
                                    <CheckCircleIcon color="success" />
                                  </ListItem>
                                ))}
                              </List>
                            </Paper>
                          </Grid>
                          {explanation.explanation_report && (
                            <Grid item xs={12}>
                              <Paper sx={{ p: 2, bgcolor: 'grey.50' }}>
                                <Typography variant="subtitle1" gutterBottom fontWeight="bold">
                                  Detailed Explanation Report
                                </Typography>
                                <Typography variant="body2" component="pre" sx={{ whiteSpace: 'pre-wrap', fontFamily: 'monospace' }}>
                                  {explanation.explanation_report}
                                </Typography>
                              </Paper>
                            </Grid>
                          )}
                        </Grid>
                      ) : (
                        <Alert severity="info">AI explainability data not available for this job</Alert>
                      )}
                    </CardContent>
                  </Card>
                </TabPanel>
              )}

              {/* Per-Bank Risk Tab */}
              {['training', 'prediction'].includes(selectedResult?.job_type) && (
                <TabPanel value={selectedTab} index={selectedResult?.job_type === 'training' ? 3 : 2}>
                  <Card>
                    <CardContent>
                      <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 2 }}>
                        <BankIcon color="primary" />
                        <Typography variant="h6">
                          Per-Bank Liquidity Risk Analysis
                        </Typography>
                      </Box>
                      <Divider sx={{ my: 2 }} />
                      {bankRisks?.banks ? (
                        <Box>
                          <Alert severity="info" sx={{ mb: 2 }}>
                            {bankRisks.summary}
                          </Alert>
                          <Grid container spacing={2}>
                            {bankRisks.banks.map((bank) => (
                              <Grid item xs={12} md={6} key={bank.bank_id}>
                                <Paper sx={{ p: 2 }}>
                                  <Typography variant="h6" gutterBottom>
                                    {bank.bank_name} ({bank.bank_id})
                                  </Typography>
                                  <Box sx={{ display: 'flex', justifyContent: 'space-between', mb: 2 }}>
                                    <RiskGauge value={bank.overall_risk_percentage} label="Overall Risk" />
                                    <Box sx={{ textAlign: 'center' }}>
                                      <Typography variant="body2" color="text.secondary">
                                        Confidence Range
                                      </Typography>
                                      <Typography variant="h6">
                                        {bank.confidence_range.lower.toFixed(1)}% - {bank.confidence_range.upper.toFixed(1)}%
                                      </Typography>
                                    </Box>
                                  </Box>
                                  <Divider sx={{ my: 1 }} />
                                  <Typography variant="subtitle2" gutterBottom>
                                    Top Vulnerabilities:
                                  </Typography>
                                  <List dense>
                                    {bank.top_vulnerabilities?.map((vuln, idx) => (
                                      <ListItem key={idx}>
                                        <WarningIcon fontSize="small" color="warning" sx={{ mr: 1 }} />
                                        <ListItemText primary={vuln} />
                                      </ListItem>
                                    ))}
                                  </List>
                                  <Typography variant="subtitle2" gutterBottom>
                                    Recommendations:
                                  </Typography>
                                  <List dense>
                                    {bank.recommendations?.map((rec, idx) => (
                                      <ListItem key={idx}>
                                        <CheckCircleIcon fontSize="small" color="success" sx={{ mr: 1 }} />
                                        <ListItemText primary={rec} />
                                      </ListItem>
                                    ))}
                                  </List>
                                  {bank.is_systemically_important && (
                                    <Alert severity="error" sx={{ mt: 1 }}>
                                      SYSTEMICALLY IMPORTANT INSTITUTION ({bank.systemic_importance_percentage.toFixed(1)}%)
                                    </Alert>
                                  )}
                                </Paper>
                              </Grid>
                            ))}
                          </Grid>
                        </Box>
                      ) : (
                        <Alert severity="info">Per-bank risk data not available. This feature requires multi-bank data.</Alert>
                      )}
                    </CardContent>
                  </Card>
                </TabPanel>
              )}

              {/* Contagion Analysis Tab */}
              {['training', 'prediction'].includes(selectedResult?.job_type) && (
                <TabPanel value={selectedTab} index={selectedResult?.job_type === 'training' ? 4 : 3}>
                  <Card>
                    <CardContent>
                      <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 2 }}>
                        <NetworkIcon color="error" />
                        <Typography variant="h6">
                          Contagion & Network Effects
                        </Typography>
                      </Box>
                      <Divider sx={{ my: 2 }} />
                      {contagionAnalysis ? (
                        <Grid container spacing={3}>
                          {/* System Health */}
                          <Grid item xs={12}>
                            <Paper sx={{ p: 2 }}>
                              <Typography variant="h6" gutterBottom>System Health</Typography>
                              <Grid container spacing={2}>
                                <Grid item xs={6} sm={3}>
                                  <RiskGauge
                                    value={contagionAnalysis.system_health?.avg_risk_percentage || 0}
                                    label="Average Risk"
                                  />
                                </Grid>
                                <Grid item xs={6} sm={3}>
                                  <RiskGauge
                                    value={contagionAnalysis.system_health?.max_risk_percentage || 0}
                                    label="Max Risk"
                                  />
                                </Grid>
                                <Grid item xs={6} sm={3}>
                                  <RiskGauge
                                    value={contagionAnalysis.system_health?.systemic_risk_percentage || 0}
                                    label="Systemic Risk"
                                  />
                                </Grid>
                                <Grid item xs={6} sm={3}>
                                  <Box sx={{ textAlign: 'center' }}>
                                    <Typography variant="h3" color="error.main">
                                      {contagionAnalysis.system_health?.num_critical_risk_banks || 0}
                                    </Typography>
                                    <Typography variant="body2" color="text.secondary">
                                      Critical Banks
                                    </Typography>
                                  </Box>
                                </Grid>
                              </Grid>
                            </Paper>
                          </Grid>

                          {/* Systemically Important Banks */}
                          {contagionAnalysis.systemic_banks?.length > 0 && (
                            <Grid item xs={12}>
                              <Paper sx={{ p: 2 }}>
                                <Typography variant="h6" gutterBottom>Systemically Important Banks</Typography>
                                <TableContainer>
                                  <Table size="small">
                                    <TableHead>
                                      <TableRow>
                                        <TableCell>Bank ID</TableCell>
                                        <TableCell>Importance</TableCell>
                                        <TableCell>Reason</TableCell>
                                      </TableRow>
                                    </TableHead>
                                    <TableBody>
                                      {contagionAnalysis.systemic_banks.map((bank) => (
                                        <TableRow key={bank.bank_id}>
                                          <TableCell>{bank.bank_id}</TableCell>
                                          <TableCell>
                                            <Chip
                                              label={`${bank.systemic_importance_percentage.toFixed(1)}%`}
                                              color="error"
                                              size="small"
                                            />
                                          </TableCell>
                                          <TableCell>{bank.reason}</TableCell>
                                        </TableRow>
                                      ))}
                                    </TableBody>
                                  </Table>
                                </TableContainer>
                              </Paper>
                            </Grid>
                          )}

                          {/* Cascade Scenarios */}
                          {contagionAnalysis.cascade_scenarios?.length > 0 && (
                            <Grid item xs={12}>
                              <Paper sx={{ p: 2 }}>
                                <Typography variant="h6" gutterBottom>Cascade Scenarios (If Bank Fails)</Typography>
                                <Alert severity="warning" sx={{ mb: 2 }}>
                                  These scenarios show what happens if a high-risk bank fails
                                </Alert>
                                <Grid container spacing={2}>
                                  {contagionAnalysis.cascade_scenarios.map((scenario) => (
                                    <Grid item xs={12} md={6} key={scenario.initial_failure}>
                                      <Paper sx={{ p: 2, bgcolor: 'error.50', border: 1, borderColor: 'error.main' }}>
                                        <Typography variant="subtitle1" fontWeight="bold" gutterBottom>
                                          If {scenario.initial_failure} fails:
                                        </Typography>
                                        <Typography variant="body2">
                                          • Total failures: <strong>{scenario.total_failures}</strong> banks
                                        </Typography>
                                        <Typography variant="body2">
                                          • Cascade depth: <strong>{scenario.cascade_depth}</strong> rounds
                                        </Typography>
                                        <Typography variant="body2" sx={{ mt: 1 }}>
                                          Affected: {scenario.affected_banks?.join(', ') || 'None'}
                                        </Typography>
                                        <Chip
                                          label={scenario.severity}
                                          color={scenario.severity === 'CRITICAL' ? 'error' : scenario.severity === 'HIGH' ? 'warning' : 'info'}
                                          size="small"
                                          sx={{ mt: 1 }}
                                        />
                                      </Paper>
                                    </Grid>
                                  ))}
                                </Grid>
                              </Paper>
                            </Grid>
                          )}

                          {/* Summary */}
                          {contagionAnalysis.summary && (
                            <Grid item xs={12}>
                              <Paper sx={{ p: 2, bgcolor: 'grey.50' }}>
                                <Typography variant="subtitle1" gutterBottom fontWeight="bold">
                                  Contagion Risk Summary
                                </Typography>
                                <Typography variant="body2" component="pre" sx={{ whiteSpace: 'pre-wrap' }}>
                                  {contagionAnalysis.summary}
                                </Typography>
                              </Paper>
                            </Grid>
                          )}
                        </Grid>
                      ) : (
                        <Alert severity="info">
                          Contagion analysis not available. This feature requires multi-bank data with exposure information.
                        </Alert>
                      )}
                    </CardContent>
                  </Card>
                </TabPanel>
              )}

              {/* Data Quality Tab */}
              {selectedResult?.job_type === 'data_collection' && (
                <TabPanel value={selectedTab} index={selectedResult?.job_type === 'training' ? 5 : (['prediction'].includes(selectedResult?.job_type) ? 4 : 1)}>
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

              {/* Raw Result Tab */}
              <TabPanel value={selectedTab} index={
                selectedResult?.job_type === 'training' ? 6 :
                selectedResult?.job_type === 'prediction' ? 5 :
                selectedResult?.job_type === 'data_collection' ? 2 : 1
              }>
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

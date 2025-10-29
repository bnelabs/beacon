import React, { useState } from 'react';
import {
  Box,
  Container,
  Typography,
  Paper,
  Grid,
  Card,
  CardContent,
  Chip,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  IconButton,
  Collapse,
  Dialog,
  DialogTitle,
  DialogContent,
  DialogActions,
  Button,
  TextField,
  MenuItem,
  Select,
  FormControl,
  InputLabel,
  Alert,
  LinearProgress,
  Stack,
  Divider,
  Tooltip
} from '@mui/material';
import {
  KeyboardArrowDown as ExpandMoreIcon,
  KeyboardArrowUp as ExpandLessIcon,
  CheckCircle as ResolveIcon,
  Delete as DeleteIcon,
  Refresh as RefreshIcon,
  ErrorOutline as ErrorIcon,
  Warning as WarningIcon,
  Info as InfoIcon
} from '@mui/icons-material';
import { useQuery, useMutation, useQueryClient } from 'react-query';
import api from '../api/client';

const ErrorAnalytics = () => {
  const queryClient = useQueryClient();
  const [expandedRow, setExpandedRow] = useState(null);
  const [resolveDialog, setResolveDialog] = useState({ open: false, errorId: null });
  const [resolutionNotes, setResolutionNotes] = useState('');
  const [filters, setFilters] = useState({
    severity: '',
    category: '',
    resolved: ''
  });

  // Fetch error statistics (refresh every 2 minutes, not time-critical)
  const { data: stats, isLoading: statsLoading } = useQuery({
    queryKey: ['error-statistics'],
    queryFn: async () => {
      return await api.errors.statistics();
    },
    refetchInterval: 120000 // Refresh every 2 minutes
  });

  // Fetch error logs (refresh every minute, not time-critical)
  const { data: errors, isLoading: errorsLoading, refetch } = useQuery({
    queryKey: ['error-logs', filters],
    queryFn: async () => {
      return await api.errors.list(filters);
    },
    refetchInterval: 60000 // Refresh every minute
  });

  // Resolve error mutation
  const resolveMutation = useMutation({
    mutationFn: async ({ errorId, notes }) => {
      return await api.errors.resolve(errorId, notes);
    },
    onSuccess: () => {
      queryClient.invalidateQueries(['error-logs']);
      queryClient.invalidateQueries(['error-statistics']);
      setResolveDialog({ open: false, errorId: null });
      setResolutionNotes('');
    }
  });

  // Delete error mutation
  const deleteMutation = useMutation({
    mutationFn: async (errorId) => {
      return await api.errors.delete(errorId);
    },
    onSuccess: () => {
      queryClient.invalidateQueries(['error-logs']);
      queryClient.invalidateQueries(['error-statistics']);
    }
  });

  const handleResolve = () => {
    if (resolveDialog.errorId && resolutionNotes.trim()) {
      resolveMutation.mutate({
        errorId: resolveDialog.errorId,
        notes: resolutionNotes
      });
    }
  };

  const handleDelete = (errorId) => {
    if (window.confirm('Are you sure you want to delete this error log?')) {
      deleteMutation.mutate(errorId);
    }
  };

  const getSeverityIcon = (severity) => {
    switch (severity.toLowerCase()) {
      case 'critical':
        return <ErrorIcon color="error" />;
      case 'error':
        return <ErrorIcon color="error" />;
      case 'warning':
        return <WarningIcon color="warning" />;
      case 'info':
        return <InfoIcon color="info" />;
      default:
        return <InfoIcon />;
    }
  };

  const getSeverityColor = (severity) => {
    switch (severity.toLowerCase()) {
      case 'critical':
        return 'error';
      case 'error':
        return 'error';
      case 'warning':
        return 'warning';
      case 'info':
        return 'info';
      default:
        return 'default';
    }
  };

  const getCategoryColor = (category) => {
    const colors = {
      network: 'primary',
      authentication: 'secondary',
      validation: 'warning',
      resource: 'error',
      permission: 'error',
      data: 'info',
      configuration: 'warning',
      system: 'default'
    };
    return colors[category.toLowerCase()] || 'default';
  };

  if (statsLoading || errorsLoading) {
    return (
      <Container maxWidth="xl" sx={{ py: 4 }}>
        <LinearProgress />
        <Typography sx={{ mt: 2 }} align="center">Loading error analytics...</Typography>
      </Container>
    );
  }

  return (
    <Container maxWidth="xl" sx={{ py: 4 }}>
      <Box sx={{ mb: 4, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <Typography variant="h4" component="h1">
          Error Analytics
        </Typography>
        <IconButton onClick={refetch} color="primary">
          <RefreshIcon />
        </IconButton>
      </Box>

      {/* Statistics Overview */}
      <Grid container spacing={3} sx={{ mb: 4 }}>
        <Grid item xs={12} md={3}>
          <Card>
            <CardContent>
              <Typography color="textSecondary" gutterBottom>
                Total Errors
              </Typography>
              <Typography variant="h3">
                {stats?.total_errors || 0}
              </Typography>
            </CardContent>
          </Card>
        </Grid>

        <Grid item xs={12} md={3}>
          <Card>
            <CardContent>
              <Typography color="textSecondary" gutterBottom>
                Last 24 Hours
              </Typography>
              <Typography variant="h3" color="primary">
                {stats?.recent_24h || 0}
              </Typography>
            </CardContent>
          </Card>
        </Grid>

        <Grid item xs={12} md={3}>
          <Card>
            <CardContent>
              <Typography color="textSecondary" gutterBottom>
                Last 7 Days
              </Typography>
              <Typography variant="h3" color="primary">
                {stats?.recent_7d || 0}
              </Typography>
            </CardContent>
          </Card>
        </Grid>

        <Grid item xs={12} md={3}>
          <Card>
            <CardContent>
              <Typography color="textSecondary" gutterBottom>
                Unresolved
              </Typography>
              <Typography variant="h3" color="error">
                {stats?.unresolved || 0}
              </Typography>
            </CardContent>
          </Card>
        </Grid>
      </Grid>

      {/* Errors by Severity and Category */}
      <Grid container spacing={3} sx={{ mb: 4 }}>
        <Grid item xs={12} md={6}>
          <Paper sx={{ p: 3 }}>
            <Typography variant="h6" gutterBottom>
              Errors by Severity
            </Typography>
            <Stack spacing={2}>
              {stats?.by_severity && Object.entries(stats.by_severity).map(([severity, count]) => (
                <Box key={severity} sx={{ display: 'flex', alignItems: 'center', gap: 2 }}>
                  <Chip
                    label={severity}
                    color={getSeverityColor(severity)}
                    size="small"
                    sx={{ minWidth: 100 }}
                  />
                  <LinearProgress
                    variant="determinate"
                    value={(count / stats.total_errors) * 100}
                    sx={{ flexGrow: 1, height: 8, borderRadius: 4 }}
                  />
                  <Typography variant="body2" sx={{ minWidth: 40, textAlign: 'right' }}>
                    {count}
                  </Typography>
                </Box>
              ))}
            </Stack>
          </Paper>
        </Grid>

        <Grid item xs={12} md={6}>
          <Paper sx={{ p: 3 }}>
            <Typography variant="h6" gutterBottom>
              Errors by Category
            </Typography>
            <Stack spacing={2}>
              {stats?.by_category && Object.entries(stats.by_category).map(([category, count]) => (
                <Box key={category} sx={{ display: 'flex', alignItems: 'center', gap: 2 }}>
                  <Chip
                    label={category}
                    color={getCategoryColor(category)}
                    size="small"
                    sx={{ minWidth: 120 }}
                  />
                  <LinearProgress
                    variant="determinate"
                    value={(count / stats.total_errors) * 100}
                    sx={{ flexGrow: 1, height: 8, borderRadius: 4 }}
                  />
                  <Typography variant="body2" sx={{ minWidth: 40, textAlign: 'right' }}>
                    {count}
                  </Typography>
                </Box>
              ))}
            </Stack>
          </Paper>
        </Grid>
      </Grid>

      {/* Most Common Errors */}
      {stats?.most_common && stats.most_common.length > 0 && (
        <Paper sx={{ p: 3, mb: 4 }}>
          <Typography variant="h6" gutterBottom>
            Most Common Errors
          </Typography>
          <TableContainer>
            <Table size="small">
              <TableHead>
                <TableRow>
                  <TableCell>Error Type</TableCell>
                  <TableCell>Category</TableCell>
                  <TableCell align="right">Occurrences</TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {stats.most_common.map((error, index) => (
                  <TableRow key={index}>
                    <TableCell>{error.error_type}</TableCell>
                    <TableCell>
                      <Chip
                        label={error.category}
                        color={getCategoryColor(error.category)}
                        size="small"
                      />
                    </TableCell>
                    <TableCell align="right">{error.occurrences}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </TableContainer>
        </Paper>
      )}

      {/* Filters */}
      <Paper sx={{ p: 3, mb: 3 }}>
        <Typography variant="h6" gutterBottom>
          Filter Errors
        </Typography>
        <Grid container spacing={2}>
          <Grid item xs={12} md={4}>
            <FormControl fullWidth>
              <InputLabel>Severity</InputLabel>
              <Select
                value={filters.severity}
                label="Severity"
                onChange={(e) => setFilters({ ...filters, severity: e.target.value })}
              >
                <MenuItem value="">All</MenuItem>
                <MenuItem value="info">Info</MenuItem>
                <MenuItem value="warning">Warning</MenuItem>
                <MenuItem value="error">Error</MenuItem>
                <MenuItem value="critical">Critical</MenuItem>
              </Select>
            </FormControl>
          </Grid>

          <Grid item xs={12} md={4}>
            <FormControl fullWidth>
              <InputLabel>Category</InputLabel>
              <Select
                value={filters.category}
                label="Category"
                onChange={(e) => setFilters({ ...filters, category: e.target.value })}
              >
                <MenuItem value="">All</MenuItem>
                <MenuItem value="network">Network</MenuItem>
                <MenuItem value="authentication">Authentication</MenuItem>
                <MenuItem value="validation">Validation</MenuItem>
                <MenuItem value="resource">Resource</MenuItem>
                <MenuItem value="permission">Permission</MenuItem>
                <MenuItem value="data">Data</MenuItem>
                <MenuItem value="configuration">Configuration</MenuItem>
                <MenuItem value="system">System</MenuItem>
              </Select>
            </FormControl>
          </Grid>

          <Grid item xs={12} md={4}>
            <FormControl fullWidth>
              <InputLabel>Status</InputLabel>
              <Select
                value={filters.resolved}
                label="Status"
                onChange={(e) => setFilters({ ...filters, resolved: e.target.value })}
              >
                <MenuItem value="">All</MenuItem>
                <MenuItem value="false">Unresolved</MenuItem>
                <MenuItem value="true">Resolved</MenuItem>
              </Select>
            </FormControl>
          </Grid>
        </Grid>
      </Paper>

      {/* Error List */}
      <Paper>
        <TableContainer>
          <Table>
            <TableHead>
              <TableRow>
                <TableCell width={50} />
                <TableCell>Severity</TableCell>
                <TableCell>Category</TableCell>
                <TableCell>Message</TableCell>
                <TableCell align="right">Occurrences</TableCell>
                <TableCell>Status</TableCell>
                <TableCell>Last Occurred</TableCell>
                <TableCell align="right">Actions</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {errors && errors.length > 0 ? (
                errors.map((error) => (
                  <React.Fragment key={error.id}>
                    <TableRow>
                      <TableCell>
                        <IconButton
                          size="small"
                          onClick={() => setExpandedRow(expandedRow === error.id ? null : error.id)}
                        >
                          {expandedRow === error.id ? <ExpandLessIcon /> : <ExpandMoreIcon />}
                        </IconButton>
                      </TableCell>
                      <TableCell>
                        <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                          {getSeverityIcon(error.severity)}
                          <Chip
                            label={error.severity}
                            color={getSeverityColor(error.severity)}
                            size="small"
                          />
                        </Box>
                      </TableCell>
                      <TableCell>
                        <Chip
                          label={error.category}
                          color={getCategoryColor(error.category)}
                          size="small"
                        />
                      </TableCell>
                      <TableCell>{error.user_message}</TableCell>
                      <TableCell align="right">
                        <Chip label={error.occurrence_count} size="small" />
                      </TableCell>
                      <TableCell>
                        {error.resolved ? (
                          <Chip label="Resolved" color="success" size="small" />
                        ) : (
                          <Chip label="Open" color="default" size="small" />
                        )}
                      </TableCell>
                      <TableCell>
                        {new Date(error.last_occurred_at).toLocaleString()}
                      </TableCell>
                      <TableCell align="right">
                        {!error.resolved && (
                          <Tooltip title="Mark as Resolved">
                            <IconButton
                              size="small"
                              onClick={() => setResolveDialog({ open: true, errorId: error.id })}
                              color="success"
                            >
                              <ResolveIcon />
                            </IconButton>
                          </Tooltip>
                        )}
                        <Tooltip title="Delete">
                          <IconButton
                            size="small"
                            onClick={() => handleDelete(error.id)}
                            color="error"
                          >
                            <DeleteIcon />
                          </IconButton>
                        </Tooltip>
                      </TableCell>
                    </TableRow>
                    <TableRow>
                      <TableCell style={{ paddingBottom: 0, paddingTop: 0 }} colSpan={8}>
                        <Collapse in={expandedRow === error.id} timeout="auto" unmountOnExit>
                          <Box sx={{ py: 3, px: 2 }}>
                            <Typography variant="h6" gutterBottom>
                              Error Details
                            </Typography>
                            <Divider sx={{ mb: 2 }} />

                            <Grid container spacing={2}>
                              <Grid item xs={12} md={6}>
                                <Typography variant="subtitle2" color="textSecondary">
                                  Error Type
                                </Typography>
                                <Typography variant="body1" gutterBottom>
                                  {error.error_type}
                                </Typography>
                              </Grid>

                              <Grid item xs={12} md={6}>
                                <Typography variant="subtitle2" color="textSecondary">
                                  First Occurred
                                </Typography>
                                <Typography variant="body1" gutterBottom>
                                  {new Date(error.created_at).toLocaleString()}
                                </Typography>
                              </Grid>

                              <Grid item xs={12}>
                                <Typography variant="subtitle2" color="textSecondary">
                                  User Message
                                </Typography>
                                <Alert severity={getSeverityColor(error.severity)} sx={{ mb: 2 }}>
                                  {error.user_message}
                                </Alert>
                              </Grid>

                              {error.technical_message && (
                                <Grid item xs={12}>
                                  <Typography variant="subtitle2" color="textSecondary">
                                    Technical Details
                                  </Typography>
                                  <Paper sx={{ p: 2, bgcolor: 'grey.100', fontFamily: 'monospace', fontSize: '0.875rem' }}>
                                    {error.technical_message}
                                  </Paper>
                                </Grid>
                              )}

                              {error.solutions && error.solutions.length > 0 && (
                                <Grid item xs={12}>
                                  <Typography variant="subtitle2" color="textSecondary" gutterBottom>
                                    Suggested Solutions
                                  </Typography>
                                  <Stack spacing={1}>
                                    {error.solutions.map((solution, index) => (
                                      <Alert key={index} severity="info">
                                        {solution}
                                      </Alert>
                                    ))}
                                  </Stack>
                                </Grid>
                              )}

                              {error.context && (
                                <Grid item xs={12}>
                                  <Typography variant="subtitle2" color="textSecondary">
                                    Context
                                  </Typography>
                                  <Typography variant="body2">
                                    {error.context}
                                  </Typography>
                                </Grid>
                              )}
                            </Grid>
                          </Box>
                        </Collapse>
                      </TableCell>
                    </TableRow>
                  </React.Fragment>
                ))
              ) : (
                <TableRow>
                  <TableCell colSpan={8} align="center">
                    <Typography color="textSecondary" sx={{ py: 4 }}>
                      No errors found
                    </Typography>
                  </TableCell>
                </TableRow>
              )}
            </TableBody>
          </Table>
        </TableContainer>
      </Paper>

      {/* Resolve Dialog */}
      <Dialog
        open={resolveDialog.open}
        onClose={() => setResolveDialog({ open: false, errorId: null })}
        maxWidth="sm"
        fullWidth
      >
        <DialogTitle>Mark Error as Resolved</DialogTitle>
        <DialogContent>
          <TextField
            autoFocus
            margin="dense"
            label="Resolution Notes"
            fullWidth
            multiline
            rows={4}
            value={resolutionNotes}
            onChange={(e) => setResolutionNotes(e.target.value)}
            placeholder="Describe how this error was resolved..."
          />
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setResolveDialog({ open: false, errorId: null })}>
            Cancel
          </Button>
          <Button
            onClick={handleResolve}
            variant="contained"
            disabled={!resolutionNotes.trim() || resolveMutation.isLoading}
          >
            Resolve
          </Button>
        </DialogActions>
      </Dialog>
    </Container>
  );
};

export default ErrorAnalytics;
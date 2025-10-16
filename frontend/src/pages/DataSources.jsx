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
  Switch,
  FormControlLabel,
  Alert,
  CircularProgress,
} from '@mui/material'
import {
  Add as AddIcon,
  Edit as EditIcon,
  Delete as DeleteIcon,
  CheckCircle as CheckIcon,
  Error as ErrorIcon,
} from '@mui/icons-material'
import { api } from '../api/client'

export default function DataSources() {
  const queryClient = useQueryClient()
  const [dialogOpen, setDialogOpen] = useState(false)
  const [editingSource, setEditingSource] = useState(null)
  const [formData, setFormData] = useState({
    name: '',
    plugin_type: 'yfinance',
    enabled: true,
    description: '',
    config: {}
  })

  // Fetch data sources
  const { data: dataSources, isLoading } = useQuery(
    'dataSources',
    () => api.dataSources.list().then(res => res.data)
  )

  // Create mutation
  const createMutation = useMutation(
    (data) => api.dataSources.create(data),
    {
      onSuccess: () => {
        queryClient.invalidateQueries('dataSources')
        handleCloseDialog()
      }
    }
  )

  // Update mutation
  const updateMutation = useMutation(
    ({ id, data }) => api.dataSources.update(id, data),
    {
      onSuccess: () => {
        queryClient.invalidateQueries('dataSources')
        handleCloseDialog()
      }
    }
  )

  // Delete mutation
  const deleteMutation = useMutation(
    (id) => api.dataSources.delete(id),
    {
      onSuccess: () => {
        queryClient.invalidateQueries('dataSources')
      }
    }
  )

  const handleOpenDialog = (source = null) => {
    if (source) {
      setEditingSource(source)
      setFormData({
        name: source.name,
        plugin_type: source.plugin_type,
        enabled: source.enabled,
        description: source.description || '',
        config: source.config
      })
    } else {
      setEditingSource(null)
      setFormData({
        name: '',
        plugin_type: 'yfinance',
        enabled: true,
        description: '',
        config: {}
      })
    }
    setDialogOpen(true)
  }

  const handleCloseDialog = () => {
    setDialogOpen(false)
    setEditingSource(null)
  }

  const handleSubmit = () => {
    if (editingSource) {
      updateMutation.mutate({ id: editingSource.id, data: formData })
    } else {
      createMutation.mutate(formData)
    }
  }

  const handleDelete = (id) => {
    if (window.confirm('Are you sure you want to delete this data source?')) {
      deleteMutation.mutate(id)
    }
  }

  if (isLoading) {
    return (
      <Box display="flex" justifyContent="center" alignItems="center" minHeight="400px">
        <CircularProgress />
      </Box>
    )
  }

  return (
    <Box>
      <Box display="flex" justifyContent="space-between" alignItems="center" mb={3}>
        <div>
          <Typography variant="h4" gutterBottom>
            Data Sources
          </Typography>
          <Typography variant="body1" color="text.secondary">
            Configure where the system gets financial data. You can add data feeds from
            Yahoo Finance, FRED, and other providers.
          </Typography>
        </div>
        <Button
          variant="contained"
          startIcon={<AddIcon />}
          onClick={() => handleOpenDialog()}
        >
          Add Data Source
        </Button>
      </Box>

      <Alert severity="info" sx={{ mb: 3 }}>
        <strong>Getting Started:</strong> Click "Add Data Source" to connect to a free
        data provider. For Yahoo Finance, no API key is needed. For FRED, you'll need to
        register for a free API key at fredapi.org.
      </Alert>

      <Card>
        <CardContent>
          <TableContainer>
            <Table>
              <TableHead>
                <TableRow>
                  <TableCell>Name</TableCell>
                  <TableCell>Type</TableCell>
                  <TableCell>Status</TableCell>
                  <TableCell>Last Updated</TableCell>
                  <TableCell>Enabled</TableCell>
                  <TableCell align="right">Actions</TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {dataSources && dataSources.length > 0 ? (
                  dataSources.map((source) => (
                    <TableRow key={source.id}>
                      <TableCell>
                        <Typography variant="body2">{source.name}</Typography>
                        {source.description && (
                          <Typography variant="caption" color="text.secondary">
                            {source.description}
                          </Typography>
                        )}
                      </TableCell>
                      <TableCell>{source.plugin_type}</TableCell>
                      <TableCell>
                        <Chip
                          icon={source.status === 'active' ? <CheckIcon /> : <ErrorIcon />}
                          label={source.status}
                          color={source.status === 'active' ? 'success' : 'error'}
                          size="small"
                        />
                      </TableCell>
                      <TableCell>
                        {source.last_successful_fetch
                          ? new Date(source.last_successful_fetch).toLocaleString()
                          : 'Never'}
                      </TableCell>
                      <TableCell>
                        <Chip
                          label={source.enabled ? 'Yes' : 'No'}
                          color={source.enabled ? 'success' : 'default'}
                          size="small"
                        />
                      </TableCell>
                      <TableCell align="right">
                        <IconButton
                          size="small"
                          onClick={() => handleOpenDialog(source)}
                        >
                          <EditIcon />
                        </IconButton>
                        <IconButton
                          size="small"
                          color="error"
                          onClick={() => handleDelete(source.id)}
                        >
                          <DeleteIcon />
                        </IconButton>
                      </TableCell>
                    </TableRow>
                  ))
                ) : (
                  <TableRow>
                    <TableCell colSpan={6} align="center">
                      <Typography color="text.secondary">
                        No data sources configured. Click "Add Data Source" to get started.
                      </Typography>
                    </TableCell>
                  </TableRow>
                )}
              </TableBody>
            </Table>
          </TableContainer>
        </CardContent>
      </Card>

      {/* Add/Edit Dialog */}
      <Dialog open={dialogOpen} onClose={handleCloseDialog} maxWidth="sm" fullWidth>
        <DialogTitle>
          {editingSource ? 'Edit Data Source' : 'Add Data Source'}
        </DialogTitle>
        <DialogContent>
          <Box sx={{ pt: 2, display: 'flex', flexDirection: 'column', gap: 2 }}>
            <TextField
              label="Name"
              fullWidth
              value={formData.name}
              onChange={(e) => setFormData({ ...formData, name: e.target.value })}
              helperText="A unique name for this data source"
            />

            <FormControl fullWidth>
              <InputLabel>Plugin Type</InputLabel>
              <Select
                value={formData.plugin_type}
                label="Plugin Type"
                onChange={(e) => setFormData({ ...formData, plugin_type: e.target.value })}
              >
                <MenuItem value="yfinance">Yahoo Finance (Free, no key needed)</MenuItem>
                <MenuItem value="fred">FRED (Free, API key required)</MenuItem>
                <MenuItem value="alpha_vantage">Alpha Vantage (Free tier, API key required)</MenuItem>
                <MenuItem value="csv">CSV File Upload</MenuItem>
                <MenuItem value="custom_api">Custom API</MenuItem>
              </Select>
            </FormControl>

            <TextField
              label="Description"
              fullWidth
              multiline
              rows={2}
              value={formData.description}
              onChange={(e) => setFormData({ ...formData, description: e.target.value })}
              helperText="Optional description of this data source"
            />

            {formData.plugin_type === 'fred' && (
              <TextField
                label="FRED API Key"
                fullWidth
                value={formData.config.api_key || ''}
                onChange={(e) => setFormData({
                  ...formData,
                  config: { ...formData.config, api_key: e.target.value }
                })}
                helperText="Get a free API key from fred.stlouisfed.org"
              />
            )}

            {formData.plugin_type === 'alpha_vantage' && (
              <TextField
                label="Alpha Vantage API Key"
                fullWidth
                value={formData.config.api_key || ''}
                onChange={(e) => setFormData({
                  ...formData,
                  config: { ...formData.config, api_key: e.target.value }
                })}
                helperText="Get a free API key from alphavantage.co"
              />
            )}

            <FormControlLabel
              control={
                <Switch
                  checked={formData.enabled}
                  onChange={(e) => setFormData({ ...formData, enabled: e.target.checked })}
                />
              }
              label="Enabled"
            />
          </Box>
        </DialogContent>
        <DialogActions>
          <Button onClick={handleCloseDialog}>Cancel</Button>
          <Button
            variant="contained"
            onClick={handleSubmit}
            disabled={!formData.name || createMutation.isLoading || updateMutation.isLoading}
          >
            {editingSource ? 'Update' : 'Add'}
          </Button>
        </DialogActions>
      </Dialog>
    </Box>
  )
}

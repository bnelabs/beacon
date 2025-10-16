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
  Tabs,
  Tab,
} from '@mui/material'
import {
  Add as AddIcon,
  Edit as EditIcon,
  Delete as DeleteIcon,
  Upload as UploadIcon,
  FilterList as FilterIcon,
} from '@mui/icons-material'
import { api } from '../api/client'

export default function Assets() {
  const queryClient = useQueryClient()
  const [dialogOpen, setDialogOpen] = useState(false)
  const [bulkDialogOpen, setBulkDialogOpen] = useState(false)
  const [editingAsset, setEditingAsset] = useState(null)
  const [activeTab, setActiveTab] = useState(0)
  const [filters, setFilters] = useState({
    enabled_only: false,
    asset_type: '',
    sector: '',
    region: ''
  })
  const [formData, setFormData] = useState({
    symbol: '',
    name: '',
    asset_type: 'stock',
    sector: '',
    region: '',
    liquidity_threshold: 0.5,
    enabled: true,
    data_source_id: null
  })
  const [bulkText, setBulkText] = useState('')

  // Fetch assets with filters
  const { data: assets, isLoading } = useQuery(
    ['assets', filters],
    () => api.assets.list(filters).then(res => res.data)
  )

  // Fetch data sources for dropdown
  const { data: dataSources } = useQuery(
    'dataSources',
    () => api.dataSources.list(true).then(res => res.data)
  )

  // Create mutation
  const createMutation = useMutation(
    (data) => api.assets.create(data),
    {
      onSuccess: () => {
        queryClient.invalidateQueries('assets')
        handleCloseDialog()
      }
    }
  )

  // Update mutation
  const updateMutation = useMutation(
    ({ id, data }) => api.assets.update(id, data),
    {
      onSuccess: () => {
        queryClient.invalidateQueries('assets')
        handleCloseDialog()
      }
    }
  )

  // Delete mutation
  const deleteMutation = useMutation(
    (id) => api.assets.delete(id),
    {
      onSuccess: () => {
        queryClient.invalidateQueries('assets')
      }
    }
  )

  // Bulk create mutation
  const bulkCreateMutation = useMutation(
    (assets) => api.assets.bulkCreate(assets),
    {
      onSuccess: () => {
        queryClient.invalidateQueries('assets')
        setBulkDialogOpen(false)
        setBulkText('')
      }
    }
  )

  const handleOpenDialog = (asset = null) => {
    if (asset) {
      setEditingAsset(asset)
      setFormData({
        symbol: asset.symbol,
        name: asset.name || '',
        asset_type: asset.asset_type || 'stock',
        sector: asset.sector || '',
        region: asset.region || '',
        liquidity_threshold: asset.liquidity_threshold || 0.5,
        enabled: asset.enabled,
        data_source_id: asset.data_source_id
      })
    } else {
      setEditingAsset(null)
      setFormData({
        symbol: '',
        name: '',
        asset_type: 'stock',
        sector: '',
        region: '',
        liquidity_threshold: 0.5,
        enabled: true,
        data_source_id: dataSources?.[0]?.id || null
      })
    }
    setDialogOpen(true)
  }

  const handleCloseDialog = () => {
    setDialogOpen(false)
    setEditingAsset(null)
  }

  const handleSubmit = () => {
    if (editingAsset) {
      updateMutation.mutate({ id: editingAsset.id, data: formData })
    } else {
      createMutation.mutate(formData)
    }
  }

  const handleDelete = (id) => {
    if (window.confirm('Are you sure you want to remove this asset from monitoring?')) {
      deleteMutation.mutate(id)
    }
  }

  const handleBulkSubmit = () => {
    const lines = bulkText.trim().split('\n')
    const assets = lines
      .filter(line => line.trim())
      .map(line => {
        const symbol = line.trim().toUpperCase()
        return {
          symbol,
          asset_type: 'stock',
          enabled: true,
          data_source_id: dataSources?.[0]?.id || 1
        }
      })

    if (assets.length > 0) {
      bulkCreateMutation.mutate(assets)
    }
  }

  const handleFilterChange = (key, value) => {
    setFilters(prev => ({ ...prev, [key]: value }))
  }

  if (isLoading) {
    return (
      <Box display="flex" justifyContent="center" alignItems="center" minHeight="400px">
        <CircularProgress />
      </Box>
    )
  }

  const uniqueTypes = [...new Set(assets?.map(a => a.asset_type).filter(Boolean))]
  const uniqueSectors = [...new Set(assets?.map(a => a.sector).filter(Boolean))]
  const uniqueRegions = [...new Set(assets?.map(a => a.region).filter(Boolean))]

  return (
    <Box>
      <Box display="flex" justifyContent="space-between" alignItems="center" mb={3}>
        <div>
          <Typography variant="h4" gutterBottom>
            Assets
          </Typography>
          <Typography variant="body1" color="text.secondary">
            Manage stocks, bonds, and other financial assets you're monitoring for liquidity risk.
          </Typography>
        </div>
        <Box display="flex" gap={1}>
          <Button
            variant="outlined"
            startIcon={<UploadIcon />}
            onClick={() => setBulkDialogOpen(true)}
          >
            Bulk Add
          </Button>
          <Button
            variant="contained"
            startIcon={<AddIcon />}
            onClick={() => handleOpenDialog()}
          >
            Add Asset
          </Button>
        </Box>
      </Box>

      <Alert severity="info" sx={{ mb: 3 }}>
        <strong>Getting Started:</strong> Add assets by symbol (e.g., JPM, AAPL, MSFT).
        For financial institutions, try: JPM, BAC, GS, MS, WFC, C, BLK, SCHW.
      </Alert>

      {/* Filters */}
      <Card sx={{ mb: 2 }}>
        <CardContent>
          <Box display="flex" alignItems="center" gap={2} flexWrap="wrap">
            <FilterIcon color="action" />
            <FormControlLabel
              control={
                <Switch
                  checked={filters.enabled_only}
                  onChange={(e) => handleFilterChange('enabled_only', e.target.checked)}
                />
              }
              label="Enabled Only"
            />
            <FormControl size="small" sx={{ minWidth: 150 }}>
              <InputLabel>Asset Type</InputLabel>
              <Select
                value={filters.asset_type}
                label="Asset Type"
                onChange={(e) => handleFilterChange('asset_type', e.target.value)}
              >
                <MenuItem value="">All Types</MenuItem>
                {uniqueTypes.map(type => (
                  <MenuItem key={type} value={type}>{type}</MenuItem>
                ))}
              </Select>
            </FormControl>
            <FormControl size="small" sx={{ minWidth: 150 }}>
              <InputLabel>Sector</InputLabel>
              <Select
                value={filters.sector}
                label="Sector"
                onChange={(e) => handleFilterChange('sector', e.target.value)}
              >
                <MenuItem value="">All Sectors</MenuItem>
                {uniqueSectors.map(sector => (
                  <MenuItem key={sector} value={sector}>{sector}</MenuItem>
                ))}
              </Select>
            </FormControl>
            <FormControl size="small" sx={{ minWidth: 150 }}>
              <InputLabel>Region</InputLabel>
              <Select
                value={filters.region}
                label="Region"
                onChange={(e) => handleFilterChange('region', e.target.value)}
              >
                <MenuItem value="">All Regions</MenuItem>
                {uniqueRegions.map(region => (
                  <MenuItem key={region} value={region}>{region}</MenuItem>
                ))}
              </Select>
            </FormControl>
          </Box>
        </CardContent>
      </Card>

      {/* Assets Table */}
      <Card>
        <CardContent>
          <TableContainer>
            <Table>
              <TableHead>
                <TableRow>
                  <TableCell>Symbol</TableCell>
                  <TableCell>Name</TableCell>
                  <TableCell>Type</TableCell>
                  <TableCell>Sector</TableCell>
                  <TableCell>Region</TableCell>
                  <TableCell>Threshold</TableCell>
                  <TableCell>Status</TableCell>
                  <TableCell align="right">Actions</TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {assets && assets.length > 0 ? (
                  assets.map((asset) => (
                    <TableRow key={asset.id}>
                      <TableCell>
                        <Typography variant="body2" fontWeight="bold">
                          {asset.symbol}
                        </Typography>
                      </TableCell>
                      <TableCell>{asset.name || '-'}</TableCell>
                      <TableCell>{asset.asset_type || '-'}</TableCell>
                      <TableCell>{asset.sector || '-'}</TableCell>
                      <TableCell>{asset.region || '-'}</TableCell>
                      <TableCell>{asset.liquidity_threshold || '-'}</TableCell>
                      <TableCell>
                        <Chip
                          label={asset.enabled ? 'Monitoring' : 'Disabled'}
                          color={asset.enabled ? 'success' : 'default'}
                          size="small"
                        />
                      </TableCell>
                      <TableCell align="right">
                        <IconButton
                          size="small"
                          onClick={() => handleOpenDialog(asset)}
                        >
                          <EditIcon />
                        </IconButton>
                        <IconButton
                          size="small"
                          color="error"
                          onClick={() => handleDelete(asset.id)}
                        >
                          <DeleteIcon />
                        </IconButton>
                      </TableCell>
                    </TableRow>
                  ))
                ) : (
                  <TableRow>
                    <TableCell colSpan={8} align="center">
                      <Typography color="text.secondary">
                        No assets configured. Click "Add Asset" to get started.
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
          {editingAsset ? 'Edit Asset' : 'Add Asset'}
        </DialogTitle>
        <DialogContent>
          <Box sx={{ pt: 2, display: 'flex', flexDirection: 'column', gap: 2 }}>
            <TextField
              label="Symbol"
              fullWidth
              value={formData.symbol}
              onChange={(e) => setFormData({ ...formData, symbol: e.target.value.toUpperCase() })}
              helperText="Ticker symbol (e.g., AAPL, JPM, MSFT)"
              disabled={!!editingAsset}
            />

            <TextField
              label="Name"
              fullWidth
              value={formData.name}
              onChange={(e) => setFormData({ ...formData, name: e.target.value })}
              helperText="Full company name (optional)"
            />

            <FormControl fullWidth>
              <InputLabel>Asset Type</InputLabel>
              <Select
                value={formData.asset_type}
                label="Asset Type"
                onChange={(e) => setFormData({ ...formData, asset_type: e.target.value })}
              >
                <MenuItem value="stock">Stock</MenuItem>
                <MenuItem value="bond">Bond</MenuItem>
                <MenuItem value="etf">ETF</MenuItem>
                <MenuItem value="crypto">Cryptocurrency</MenuItem>
                <MenuItem value="commodity">Commodity</MenuItem>
                <MenuItem value="forex">Forex</MenuItem>
              </Select>
            </FormControl>

            <TextField
              label="Sector"
              fullWidth
              value={formData.sector}
              onChange={(e) => setFormData({ ...formData, sector: e.target.value })}
              helperText="e.g., Financial Services, Technology"
            />

            <TextField
              label="Region"
              fullWidth
              value={formData.region}
              onChange={(e) => setFormData({ ...formData, region: e.target.value })}
              helperText="e.g., North America, Europe, Asia"
            />

            <TextField
              label="Liquidity Threshold"
              type="number"
              fullWidth
              value={formData.liquidity_threshold}
              onChange={(e) => setFormData({ ...formData, liquidity_threshold: parseFloat(e.target.value) })}
              helperText="Alert threshold for liquidity risk (0.0 to 1.0)"
              inputProps={{ min: 0, max: 1, step: 0.1 }}
            />

            <FormControl fullWidth>
              <InputLabel>Data Source</InputLabel>
              <Select
                value={formData.data_source_id || ''}
                label="Data Source"
                onChange={(e) => setFormData({ ...formData, data_source_id: e.target.value })}
              >
                {dataSources && dataSources.map(ds => (
                  <MenuItem key={ds.id} value={ds.id}>{ds.name}</MenuItem>
                ))}
              </Select>
            </FormControl>

            <FormControlLabel
              control={
                <Switch
                  checked={formData.enabled}
                  onChange={(e) => setFormData({ ...formData, enabled: e.target.checked })}
                />
              }
              label="Enable Monitoring"
            />
          </Box>
        </DialogContent>
        <DialogActions>
          <Button onClick={handleCloseDialog}>Cancel</Button>
          <Button
            variant="contained"
            onClick={handleSubmit}
            disabled={!formData.symbol || !formData.data_source_id || createMutation.isLoading || updateMutation.isLoading}
          >
            {editingAsset ? 'Update' : 'Add'}
          </Button>
        </DialogActions>
      </Dialog>

      {/* Bulk Add Dialog */}
      <Dialog open={bulkDialogOpen} onClose={() => setBulkDialogOpen(false)} maxWidth="sm" fullWidth>
        <DialogTitle>Bulk Add Assets</DialogTitle>
        <DialogContent>
          <Box sx={{ pt: 2 }}>
            <Alert severity="info" sx={{ mb: 2 }}>
              Enter one ticker symbol per line. All assets will use the first available data source.
            </Alert>
            <TextField
              multiline
              rows={10}
              fullWidth
              placeholder="AAPL&#10;JPM&#10;MSFT&#10;GS&#10;BAC"
              value={bulkText}
              onChange={(e) => setBulkText(e.target.value)}
              helperText={`${bulkText.trim().split('\n').filter(l => l.trim()).length} symbols`}
            />
          </Box>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setBulkDialogOpen(false)}>Cancel</Button>
          <Button
            variant="contained"
            onClick={handleBulkSubmit}
            disabled={!bulkText.trim() || bulkCreateMutation.isLoading}
          >
            Add All
          </Button>
        </DialogActions>
      </Dialog>
    </Box>
  )
}

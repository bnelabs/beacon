import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from 'react-query'
import {
  Box,
  Container,
  Typography,
  Card,
  CardContent,
  Grid,
  TextField,
  InputAdornment,
  Chip,
  Button,
  FormControl,
  InputLabel,
  Select,
  MenuItem,
  Alert,
  Snackbar,
  IconButton,
  Tooltip,
  Paper,
  Divider,
  TablePagination
} from '@mui/material'
import {
  Search as SearchIcon,
  FilterList as FilterIcon,
  LibraryBooks as CatalogueIcon,
  Add as AddIcon,
  CheckCircle as CheckCircleIcon,
  Public as PublicIcon,
  TrendingUp as TrendingUpIcon,
  AttachMoney as MoneyIcon,
  AccountBalance as BankIcon,
  ShowChart as ChartIcon,
  PlayArrow as TestIcon
} from '@mui/icons-material'
import { api } from '../api/client'

function CategoryIcon({ category }) {
  const icons = {
    banking: <BankIcon />,
    stocks: <ChartIcon />,
    bonds: <MoneyIcon />,
    exchange_rates: <PublicIcon />,
    interest_rates: <TrendingUpIcon />,
    money_market: <MoneyIcon />,
    credit_markets: <MoneyIcon />,
    commodities: <PublicIcon />,
    economic_indicators: <TrendingUpIcon />,
    central_bank: <BankIcon />,
    derivatives: <ChartIcon />,
    forex: <PublicIcon />
  }
  return icons[category] || <CatalogueIcon />
}

export default function Catalogue() {
  const [searchQuery, setSearchQuery] = useState('')
  const [categoryFilter, setCategoryFilter] = useState('')
  const [regionFilter, setRegionFilter] = useState('')
  const [sourceFilter, setSourceFilter] = useState('')
  const [riskFilter, setRiskFilter] = useState('')
  const [page, setPage] = useState(0)
  const [rowsPerPage, setRowsPerPage] = useState(12)
  const [snackbar, setSnackbar] = useState({ open: false, message: '', severity: 'success' })

  const queryClient = useQueryClient()

  // Fetch catalogue items
  const { data: catalogueData, isLoading } = useQuery({
    queryKey: ['catalogue', categoryFilter, regionFilter, sourceFilter],
    queryFn: async () => {
      const params = { enabled_only: false }
      if (categoryFilter) params.category = categoryFilter
      if (regionFilter) params.region = regionFilter
      if (sourceFilter) params.source = sourceFilter
      const response = await api.catalogue.list(params)
      // Response is array of items directly
      return { items: response.data }
    }
  })

  // Fetch categories
  const { data: categories } = useQuery({
    queryKey: ['catalogue-categories'],
    queryFn: async () => {
      const response = await api.catalogue.categories()
      return response.data
    }
  })

  // Fetch regions
  const { data: regions } = useQuery({
    queryKey: ['catalogue-regions'],
    queryFn: async () => {
      const response = await api.catalogue.regions()
      return response.data
    }
  })

  // Add to monitoring mutation
  const addToMonitoringMutation = useMutation({
    mutationFn: async (catalogueItem) => {
      const assetData = {
        symbol: catalogueItem.code,
        name: catalogueItem.name,
        asset_type: 'macro_indicator',
        sector: categoryFilter || 'Financial',
        region: catalogueItem.region,
        liquidity_threshold: 0.5,
        enabled: true,
        data_source_id: catalogueItem.data_source_id
      }
      return await api.assets.create(assetData)
    },
    onSuccess: () => {
      queryClient.invalidateQueries(['assets'])
      setSnackbar({ open: true, message: 'Added to monitoring successfully!', severity: 'success' })
    },
    onError: (error) => {
      const errorMsg = error.response?.data?.detail?.user_friendly ||
                       error.response?.data?.detail ||
                       error.userFriendlyMessage ||
                       'Failed to add to monitoring'
      setSnackbar({
        open: true,
        message: errorMsg,
        severity: 'error'
      })
    }
  })

  // Test catalogue item mutation
  const testItemMutation = useMutation({
    mutationFn: async (itemId) => {
      return await api.catalogue.test(itemId)
    },
    onSuccess: (data) => {
      if (data.data.success) {
        setSnackbar({
          open: true,
          message: `✓ ${data.data.item_name}: ${data.data.message}`,
          severity: 'success'
        })
      } else {
        setSnackbar({
          open: true,
          message: `✗ ${data.data.item_name}: ${data.data.message}`,
          severity: 'warning'
        })
      }
    },
    onError: (error) => {
      const errorMsg = error.response?.data?.detail?.user_friendly ||
                       error.response?.data?.message ||
                       error.userFriendlyMessage ||
                       'Failed to test data source'
      setSnackbar({
        open: true,
        message: errorMsg,
        severity: 'error'
      })
    }
  })

  // Filter items by search query
  const filteredItems = catalogueData?.items?.filter(item => {
    const searchLower = searchQuery.toLowerCase()
    const matchesSearch = !searchQuery ||
      item.name.toLowerCase().includes(searchLower) ||
      item.description.toLowerCase().includes(searchLower) ||
      item.code.toLowerCase().includes(searchLower) ||
      item.tags?.some(tag => tag.toLowerCase().includes(searchLower))

    const matchesRisk = !riskFilter || item.risk_types?.includes(riskFilter)

    return matchesSearch && matchesRisk
  }) || []

  // Pagination
  const paginatedItems = filteredItems.slice(
    page * rowsPerPage,
    page * rowsPerPage + rowsPerPage
  )

  const handleChangePage = (event, newPage) => {
    setPage(newPage)
  }

  const handleChangeRowsPerPage = (event) => {
    setRowsPerPage(parseInt(event.target.value, 10))
    setPage(0)
  }

  const getRiskColor = (riskType) => {
    const colors = {
      systemic_risk: 'error',
      funding_liquidity: 'warning',
      market_liquidity: 'info',
      credit_risk: 'secondary',
      operational_risk: 'default'
    }
    return colors[riskType] || 'default'
  }

  const getFrequencyColor = (frequency) => {
    const colors = {
      daily: 'success',
      weekly: 'info',
      monthly: 'warning',
      quarterly: 'secondary',
      annual: 'default'
    }
    return colors[frequency] || 'default'
  }

  return (
    <Container maxWidth="xl" sx={{ mt: 4, mb: 4 }}>
      {/* Header */}
      <Box sx={{ mb: 4 }}>
        <Typography variant="h4" gutterBottom sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
          <CatalogueIcon fontSize="large" />
          Data Catalogue
        </Typography>
        <Typography variant="body1" color="text.secondary">
          Browse and add data sources to monitoring. {filteredItems.length} items available.
        </Typography>
      </Box>

      {/* Filters */}
      <Paper sx={{ p: 3, mb: 3 }}>
        <Grid container spacing={2}>
          {/* Search */}
          <Grid item xs={12} md={4}>
            <TextField
              fullWidth
              placeholder="Search by name, code, or tag..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              InputProps={{
                startAdornment: (
                  <InputAdornment position="start">
                    <SearchIcon />
                  </InputAdornment>
                )
              }}
            />
          </Grid>

          {/* Category Filter */}
          <Grid item xs={12} sm={6} md={2}>
            <FormControl fullWidth>
              <InputLabel>Category</InputLabel>
              <Select
                value={categoryFilter}
                label="Category"
                onChange={(e) => setCategoryFilter(e.target.value)}
              >
                <MenuItem value="">All Categories</MenuItem>
                {categories?.categories?.map((cat) => (
                  <MenuItem key={cat} value={cat}>
                    {cat.replace(/_/g, ' ').toUpperCase()}
                  </MenuItem>
                ))}
              </Select>
            </FormControl>
          </Grid>

          {/* Region Filter */}
          <Grid item xs={12} sm={6} md={2}>
            <FormControl fullWidth>
              <InputLabel>Region</InputLabel>
              <Select
                value={regionFilter}
                label="Region"
                onChange={(e) => setRegionFilter(e.target.value)}
              >
                <MenuItem value="">All Regions</MenuItem>
                {regions?.regions?.map((region) => (
                  <MenuItem key={region} value={region}>
                    {region.replace(/_/g, ' ').toUpperCase()}
                  </MenuItem>
                ))}
              </Select>
            </FormControl>
          </Grid>

          {/* Data Source Filter */}
          <Grid item xs={12} sm={6} md={2}>
            <FormControl fullWidth>
              <InputLabel>Data Source</InputLabel>
              <Select
                value={sourceFilter}
                label="Data Source"
                onChange={(e) => setSourceFilter(e.target.value)}
              >
                <MenuItem value="">All Sources</MenuItem>
                <MenuItem value="ECB">ECB</MenuItem>
                <MenuItem value="FRED">FRED</MenuItem>
                <MenuItem value="Yahoo Finance">Yahoo Finance</MenuItem>
                <MenuItem value="Alpha Vantage">Alpha Vantage</MenuItem>
                <MenuItem value="SEC EDGAR">SEC EDGAR</MenuItem>
                <MenuItem value="World Bank">World Bank</MenuItem>
                <MenuItem value="BIS">BIS</MenuItem>
                <MenuItem value="IMF">IMF</MenuItem>
              </Select>
            </FormControl>
          </Grid>

          {/* Risk Type Filter */}
          <Grid item xs={12} sm={6} md={2}>
            <FormControl fullWidth>
              <InputLabel>Risk Type</InputLabel>
              <Select
                value={riskFilter}
                label="Risk Type"
                onChange={(e) => setRiskFilter(e.target.value)}
              >
                <MenuItem value="">All Risk Types</MenuItem>
                <MenuItem value="systemic_risk">Systemic Risk</MenuItem>
                <MenuItem value="market_liquidity">Market Liquidity</MenuItem>
                <MenuItem value="funding_liquidity">Funding Liquidity</MenuItem>
                <MenuItem value="credit_risk">Credit Risk</MenuItem>
                <MenuItem value="operational_risk">Operational Risk</MenuItem>
              </Select>
            </FormControl>
          </Grid>
        </Grid>
      </Paper>

      {/* Results */}
      {isLoading ? (
        <Alert severity="info">Loading catalogue...</Alert>
      ) : filteredItems.length === 0 ? (
        <Alert severity="warning">No items found matching your filters</Alert>
      ) : (
        <>
          <Grid container spacing={3}>
            {paginatedItems.map((item) => (
              <Grid item xs={12} sm={6} md={4} key={item.id}>
                <Card sx={{ height: '100%', display: 'flex', flexDirection: 'column' }}>
                  <CardContent sx={{ flexGrow: 1 }}>
                    {/* Header */}
                    <Box sx={{ display: 'flex', alignItems: 'flex-start', mb: 2 }}>
                      <CategoryIcon category={item.category} />
                      <Box sx={{ ml: 1, flexGrow: 1 }}>
                        <Typography variant="h6" component="div" sx={{ fontSize: '1rem', fontWeight: 'bold' }}>
                          {item.name}
                        </Typography>
                        <Typography variant="body2" color="text.secondary" sx={{ fontSize: '0.75rem' }}>
                          {item.code}
                        </Typography>
                      </Box>
                      {item.default_selected && (
                        <Tooltip title="Default Selected">
                          <CheckCircleIcon color="success" fontSize="small" />
                        </Tooltip>
                      )}
                    </Box>

                    {/* Description */}
                    <Typography variant="body2" color="text.secondary" sx={{ mb: 2, minHeight: 40 }}>
                      {item.description}
                    </Typography>

                    {/* Metadata */}
                    <Box sx={{ mb: 2 }}>
                      <Grid container spacing={1}>
                        <Grid item xs={6}>
                          <Typography variant="caption" color="text.secondary">Source</Typography>
                          <Typography variant="body2" sx={{ fontWeight: 'bold' }}>
                            {item.data_source?.name || 'N/A'}
                          </Typography>
                        </Grid>
                        <Grid item xs={6}>
                          <Typography variant="caption" color="text.secondary">Frequency</Typography>
                          <Chip
                            label={item.frequency}
                            size="small"
                            color={getFrequencyColor(item.frequency)}
                            sx={{ mt: 0.5 }}
                          />
                        </Grid>
                        <Grid item xs={6}>
                          <Typography variant="caption" color="text.secondary">Region</Typography>
                          <Typography variant="body2">
                            {item.region?.replace(/_/g, ' ').toUpperCase()}
                          </Typography>
                        </Grid>
                        <Grid item xs={6}>
                          <Typography variant="caption" color="text.secondary">Unit</Typography>
                          <Typography variant="body2">{item.unit}</Typography>
                        </Grid>
                      </Grid>
                    </Box>

                    {/* Risk Types */}
                    {item.risk_types && item.risk_types.length > 0 && (
                      <Box sx={{ mb: 2 }}>
                        <Typography variant="caption" color="text.secondary" gutterBottom>
                          Risk Types
                        </Typography>
                        <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 0.5, mt: 0.5 }}>
                          {item.risk_types.map((risk) => (
                            <Chip
                              key={risk}
                              label={risk.replace(/_/g, ' ')}
                              size="small"
                              color={getRiskColor(risk)}
                              sx={{ fontSize: '0.65rem' }}
                            />
                          ))}
                        </Box>
                      </Box>
                    )}

                    {/* Tags */}
                    {item.tags && item.tags.length > 0 && (
                      <Box sx={{ mb: 1 }}>
                        <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 0.5 }}>
                          {item.tags.slice(0, 3).map((tag) => (
                            <Chip
                              key={tag}
                              label={tag}
                              size="small"
                              variant="outlined"
                              sx={{ fontSize: '0.65rem' }}
                            />
                          ))}
                        </Box>
                      </Box>
                    )}
                  </CardContent>

                  <Divider />

                  {/* Actions */}
                  <Box sx={{ p: 2, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                    <Box sx={{ display: 'flex', gap: 1, alignItems: 'center' }}>
                      <Chip
                        label={`Priority: ${item.priority}`}
                        size="small"
                        color={item.priority >= 90 ? 'success' : item.priority >= 80 ? 'info' : 'default'}
                      />
                      <Tooltip title="Test if this data source is currently accessible">
                        <IconButton
                          size="small"
                          color="primary"
                          onClick={() => testItemMutation.mutate(item.id)}
                          disabled={testItemMutation.isLoading}
                        >
                          <TestIcon />
                        </IconButton>
                      </Tooltip>
                    </Box>
                    <Button
                      variant="contained"
                      size="small"
                      startIcon={<AddIcon />}
                      onClick={() => addToMonitoringMutation.mutate(item)}
                      disabled={addToMonitoringMutation.isLoading}
                    >
                      Add to Monitoring
                    </Button>
                  </Box>
                </Card>
              </Grid>
            ))}
          </Grid>

          {/* Pagination */}
          <Box sx={{ mt: 3, display: 'flex', justifyContent: 'center' }}>
            <TablePagination
              component="div"
              count={filteredItems.length}
              page={page}
              onPageChange={handleChangePage}
              rowsPerPage={rowsPerPage}
              onRowsPerPageChange={handleChangeRowsPerPage}
              rowsPerPageOptions={[12, 24, 48]}
            />
          </Box>
        </>
      )}

      {/* Snackbar */}
      <Snackbar
        open={snackbar.open}
        autoHideDuration={4000}
        onClose={() => setSnackbar({ ...snackbar, open: false })}
        anchorOrigin={{ vertical: 'bottom', horizontal: 'center' }}
      >
        <Alert
          onClose={() => setSnackbar({ ...snackbar, open: false })}
          severity={snackbar.severity}
          sx={{ width: '100%' }}
        >
          {snackbar.message}
        </Alert>
      </Snackbar>
    </Container>
  )
}

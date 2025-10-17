import { useState, useEffect } from 'react'
import {
  Dialog,
  DialogTitle,
  DialogContent,
  DialogActions,
  Button,
  TextField,
  FormControl,
  InputLabel,
  Select,
  MenuItem,
  Box,
  Stepper,
  Step,
  StepLabel,
  Typography,
  Alert,
  Chip,
  FormControlLabel,
  Switch,
  Paper,
  List,
  ListItem,
  ListItemText,
} from '@mui/material'
import {
  TrendingUp as StockIcon,
  AccountBalance as BankIcon,
  ShowChart as ChartIcon,
  Public as GlobalIcon,
} from '@mui/icons-material'

// Data source compatibility mapping
const DATA_SOURCE_COMPATIBILITY = {
  'Yahoo Finance': {
    compatible: ['stock', 'etf', 'crypto', 'forex'],
    recommended: ['stock', 'etf'],
    examples: {
      stock: 'JPM, AAPL, MSFT, GS, BAC',
      etf: 'SPY, QQQ, VTI',
      crypto: 'BTC-USD, ETH-USD',
      forex: 'EURUSD=X',
    },
    description: 'Real-time stock market data, ETFs, and cryptocurrency prices'
  },
  'Alpha Vantage': {
    compatible: ['stock', 'crypto', 'forex'],
    recommended: ['stock'],
    examples: {
      stock: 'IBM, GOOGL, AMZN',
      crypto: 'BTC, ETH',
      forex: 'EUR/USD',
    },
    description: 'Financial market data with technical indicators'
  },
  'FRED': {
    compatible: ['bond', 'macro_indicator'],
    recommended: ['bond', 'macro_indicator'],
    examples: {
      bond: 'DGS10, DGS2, DGS30',
      macro_indicator: 'GDP, UNRATE, CPIAUCSL',
    },
    description: 'Economic indicators, interest rates, and government data'
  },
  'ECB': {
    compatible: ['forex', 'macro_indicator', 'bond'],
    recommended: ['forex'],
    examples: {
      forex: 'USD, GBP, JPY, CHF',
      macro_indicator: 'HICP, M3',
      bond: 'Euro Area Government Bonds',
    },
    description: 'European Central Bank data - exchange rates and economic indicators'
  },
}

export default function SmartAssetDialog({ open, onClose, onSubmit, dataSources, editingAsset }) {
  const [activeStep, setActiveStep] = useState(0)
  const [formData, setFormData] = useState({
    symbol: '',
    name: '',
    asset_type: '',
    sector: '',
    region: '',
    liquidity_threshold: 0.5,
    enabled: true,
    data_source_id: null
  })
  const [selectedDataSource, setSelectedDataSource] = useState(null)
  const [compatibleSources, setCompatibleSources] = useState([])
  const [showWarning, setShowWarning] = useState(false)

  const steps = editingAsset
    ? ['Edit Details']
    : ['Choose Asset Type', 'Select Data Source', 'Enter Details']

  // Reset form when dialog opens
  useEffect(() => {
    if (open && !editingAsset) {
      setActiveStep(0)
      setFormData({
        symbol: '',
        name: '',
        asset_type: '',
        sector: '',
        region: '',
        liquidity_threshold: 0.5,
        enabled: true,
        data_source_id: null
      })
      setSelectedDataSource(null)
      setShowWarning(false)
    } else if (open && editingAsset) {
      setFormData({
        symbol: editingAsset.symbol,
        name: editingAsset.name || '',
        asset_type: editingAsset.asset_type || 'stock',
        sector: editingAsset.sector || '',
        region: editingAsset.region || '',
        liquidity_threshold: editingAsset.liquidity_threshold || 0.5,
        enabled: editingAsset.enabled,
        data_source_id: editingAsset.data_source_id
      })
      const ds = dataSources?.find(d => d.id === editingAsset.data_source_id)
      setSelectedDataSource(ds)
    }
  }, [open, editingAsset, dataSources])

  // Update compatible sources when asset type changes
  useEffect(() => {
    if (formData.asset_type && dataSources) {
      const compatible = dataSources.filter(ds => {
        const compat = DATA_SOURCE_COMPATIBILITY[ds.name]
        return compat && compat.compatible.includes(formData.asset_type)
      })
      setCompatibleSources(compatible)

      // Auto-select if only one compatible source
      if (compatible.length === 1) {
        handleDataSourceSelect(compatible[0])
      }
    }
  }, [formData.asset_type, dataSources])

  const handleAssetTypeSelect = (type) => {
    setFormData({ ...formData, asset_type: type })
    setActiveStep(1)
  }

  const handleDataSourceSelect = (dataSource) => {
    setSelectedDataSource(dataSource)
    setFormData({ ...formData, data_source_id: dataSource.id })

    // Check compatibility and show warning if needed
    const compat = DATA_SOURCE_COMPATIBILITY[dataSource.name]
    if (compat && !compat.compatible.includes(formData.asset_type)) {
      setShowWarning(true)
    } else {
      setShowWarning(false)
      if (!editingAsset) {
        setActiveStep(2)
      }
    }
  }

  const handleBack = () => {
    setActiveStep((prev) => prev - 1)
    setShowWarning(false)
  }

  const handleNext = () => {
    setActiveStep((prev) => prev + 1)
  }

  const handleSubmit = () => {
    onSubmit(formData)
    onClose()
  }

  const isStepComplete = (step) => {
    switch (step) {
      case 0:
        return !!formData.asset_type
      case 1:
        return !!formData.data_source_id
      case 2:
        return !!formData.symbol
      default:
        return false
    }
  }

  const getExampleSymbols = () => {
    if (!selectedDataSource || !formData.asset_type) return ''
    const compat = DATA_SOURCE_COMPATIBILITY[selectedDataSource.name]
    return compat?.examples[formData.asset_type] || ''
  }

  const isRecommendedCombination = () => {
    if (!selectedDataSource || !formData.asset_type) return false
    const compat = DATA_SOURCE_COMPATIBILITY[selectedDataSource.name]
    return compat?.recommended?.includes(formData.asset_type) || false
  }

  return (
    <Dialog open={open} onClose={onClose} maxWidth="md" fullWidth>
      <DialogTitle>
        {editingAsset ? 'Edit Asset' : 'Add New Asset to Monitoring'}
      </DialogTitle>

      <DialogContent>
        {!editingAsset && (
          <Box sx={{ mb: 3 }}>
            <Stepper activeStep={activeStep}>
              {steps.map((label) => (
                <Step key={label}>
                  <StepLabel>{label}</StepLabel>
                </Step>
              ))}
            </Stepper>
          </Box>
        )}

        {/* Step 0: Choose Asset Type */}
        {!editingAsset && activeStep === 0 && (
          <Box>
            <Typography variant="h6" gutterBottom>
              What type of asset do you want to monitor?
            </Typography>
            <Typography variant="body2" color="text.secondary" sx={{ mb: 3 }}>
              This helps us show you compatible data sources
            </Typography>

            <Box sx={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: 2 }}>
              {[
                { value: 'stock', label: 'Stock', icon: <StockIcon />, desc: 'Public company shares' },
                { value: 'etf', label: 'ETF', icon: <ChartIcon />, desc: 'Exchange-traded funds' },
                { value: 'bond', label: 'Bond', icon: <BankIcon />, desc: 'Fixed income securities' },
                { value: 'forex', label: 'Forex', icon: <GlobalIcon />, desc: 'Currency pairs' },
                { value: 'crypto', label: 'Crypto', icon: <ChartIcon />, desc: 'Cryptocurrency' },
                { value: 'macro_indicator', label: 'Economic Indicator', icon: <BankIcon />, desc: 'GDP, inflation, etc.' },
              ].map((type) => (
                <Paper
                  key={type.value}
                  sx={{
                    p: 2,
                    cursor: 'pointer',
                    border: formData.asset_type === type.value ? '2px solid' : '1px solid',
                    borderColor: formData.asset_type === type.value ? 'primary.main' : 'divider',
                    '&:hover': { borderColor: 'primary.main', bgcolor: 'action.hover' }
                  }}
                  onClick={() => handleAssetTypeSelect(type.value)}
                >
                  <Box sx={{ display: 'flex', alignItems: 'center', mb: 1 }}>
                    {type.icon}
                    <Typography variant="h6" sx={{ ml: 1 }}>
                      {type.label}
                    </Typography>
                  </Box>
                  <Typography variant="body2" color="text.secondary">
                    {type.desc}
                  </Typography>
                </Paper>
              ))}
            </Box>
          </Box>
        )}

        {/* Step 1: Select Data Source */}
        {!editingAsset && activeStep === 1 && (
          <Box>
            <Typography variant="h6" gutterBottom>
              Select a data source
            </Typography>
            <Typography variant="body2" color="text.secondary" sx={{ mb: 3 }}>
              These sources are compatible with {formData.asset_type}
            </Typography>

            {compatibleSources.length === 0 && (
              <Alert severity="warning">
                No data sources are configured for this asset type. Please configure a data source first.
              </Alert>
            )}

            <List>
              {compatibleSources.map((ds) => {
                const compat = DATA_SOURCE_COMPATIBILITY[ds.name]
                const recommended = compat?.recommended?.includes(formData.asset_type)

                return (
                  <Paper
                    key={ds.id}
                    sx={{
                      mb: 2,
                      cursor: 'pointer',
                      border: selectedDataSource?.id === ds.id ? '2px solid' : '1px solid',
                      borderColor: selectedDataSource?.id === ds.id ? 'primary.main' : 'divider',
                      '&:hover': { borderColor: 'primary.main', bgcolor: 'action.hover' }
                    }}
                    onClick={() => handleDataSourceSelect(ds)}
                  >
                    <ListItem>
                      <ListItemText
                        primary={
                          <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                            <Typography variant="subtitle1">{ds.name}</Typography>
                            {recommended && <Chip label="Recommended" size="small" color="success" />}
                          </Box>
                        }
                        secondary={
                          <>
                            <Typography variant="body2" color="text.secondary">
                              {compat?.description}
                            </Typography>
                            {compat?.examples[formData.asset_type] && (
                              <Typography variant="caption" sx={{ display: 'block', mt: 0.5 }}>
                                Examples: {compat.examples[formData.asset_type]}
                              </Typography>
                            )}
                          </>
                        }
                      />
                    </ListItem>
                  </Paper>
                )
              })}
            </List>

            {showWarning && (
              <Alert severity="warning" sx={{ mt: 2 }}>
                This combination may not work as expected. Please select a compatible data source.
              </Alert>
            )}
          </Box>
        )}

        {/* Step 2: Enter Details */}
        {(editingAsset || activeStep === 2) && (
          <Box>
            <Typography variant="h6" gutterBottom>
              Enter asset details
            </Typography>

            {selectedDataSource && isRecommendedCombination() && (
              <Alert severity="success" sx={{ mb: 2 }}>
                <strong>Great choice!</strong> {selectedDataSource.name} is recommended for {formData.asset_type}s.
                {getExampleSymbols() && (
                  <Typography variant="body2" sx={{ mt: 1 }}>
                    Try these symbols: {getExampleSymbols()}
                  </Typography>
                )}
              </Alert>
            )}

            <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2, mt: 2 }}>
              <TextField
                label="Symbol / Code"
                fullWidth
                required
                value={formData.symbol}
                onChange={(e) => setFormData({ ...formData, symbol: e.target.value.toUpperCase() })}
                helperText={getExampleSymbols() ? `Examples: ${getExampleSymbols()}` : 'Enter ticker symbol or code'}
                disabled={!!editingAsset}
              />

              <TextField
                label="Name"
                fullWidth
                value={formData.name}
                onChange={(e) => setFormData({ ...formData, name: e.target.value })}
                helperText="Full name (optional, will be auto-filled if available)"
              />

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

              <FormControlLabel
                control={
                  <Switch
                    checked={formData.enabled}
                    onChange={(e) => setFormData({ ...formData, enabled: e.target.checked })}
                  />
                }
                label="Enable Monitoring"
              />

              <Alert severity="info">
                <Typography variant="body2">
                  <strong>Data Source:</strong> {selectedDataSource?.name}
                </Typography>
                <Typography variant="body2">
                  <strong>Asset Type:</strong> {formData.asset_type}
                </Typography>
              </Alert>
            </Box>
          </Box>
        )}
      </DialogContent>

      <DialogActions>
        <Button onClick={onClose}>Cancel</Button>

        {!editingAsset && activeStep > 0 && (
          <Button onClick={handleBack}>Back</Button>
        )}

        {!editingAsset && activeStep < 2 && (
          <Button
            variant="contained"
            onClick={handleNext}
            disabled={!isStepComplete(activeStep)}
          >
            Next
          </Button>
        )}

        {(editingAsset || activeStep === 2) && (
          <Button
            variant="contained"
            onClick={handleSubmit}
            disabled={!formData.symbol || !formData.data_source_id}
          >
            {editingAsset ? 'Update' : 'Add Asset'}
          </Button>
        )}
      </DialogActions>
    </Dialog>
  )
}

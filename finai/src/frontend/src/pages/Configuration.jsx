import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from 'react-query'
import {
  Box,
  Card,
  CardContent,
  Typography,
  TextField,
  Button,
  Alert,
  CircularProgress,
  Tabs,
  Tab,
  Grid,
  Slider,
} from '@mui/material'
import { Save as SaveIcon } from '@mui/icons-material'
import { api } from '../api/client'

function TabPanel({ children, value, index }) {
  return (
    <div hidden={value !== index}>
      {value === index && <Box sx={{ pt: 3 }}>{children}</Box>}
    </div>
  )
}

export default function Configuration() {
  const queryClient = useQueryClient()
  const [activeTab, setActiveTab] = useState(0)
  const [modelParams, setModelParams] = useState({})
  const [dataParams, setDataParams] = useState({})
  const [trainingParams, setTrainingParams] = useState({})

  // Fetch config
  const { data: config, isLoading } = useQuery(
    'config',
    () => api.config.get().then(res => res.data),
    {
      onSuccess: (data) => {
        setModelParams(data.model_params)
        setDataParams(data.data_params)
        setTrainingParams(data.training_params)
      }
    }
  )

  // Update mutations
  const updateModelMutation = useMutation(
    (data) => api.config.updateModel(data),
    {
      onSuccess: () => {
        queryClient.invalidateQueries('config')
      }
    }
  )

  const updateDataMutation = useMutation(
    (data) => api.config.updateData(data),
    {
      onSuccess: () => {
        queryClient.invalidateQueries('config')
      }
    }
  )

  const updateTrainingMutation = useMutation(
    (data) => api.config.updateTraining(data),
    {
      onSuccess: () => {
        queryClient.invalidateQueries('config')
      }
    }
  )

  if (isLoading) {
    return (
      <Box display="flex" justifyContent="center" alignItems="center" minHeight="400px">
        <CircularProgress />
      </Box>
    )
  }

  return (
    <Box>
      <Typography variant="h4" gutterBottom>
        System Configuration
      </Typography>
      <Typography variant="body1" color="text.secondary" paragraph>
        Adjust model, data collection, and training parameters. Changes take effect on the next job.
      </Typography>

      <Alert severity="info" sx={{ mb: 3 }}>
        <strong>Tip:</strong> If you're running out of memory, reduce the batch size and hidden dimension.
        Check the System Status page for resource-based recommendations.
      </Alert>

      <Card>
        <CardContent>
          <Tabs value={activeTab} onChange={(e, v) => setActiveTab(v)}>
            <Tab label="Model Parameters" />
            <Tab label="Data Collection" />
            <Tab label="Training" />
          </Tabs>

          {/* Model Parameters Tab */}
          <TabPanel value={activeTab} index={0}>
            <Grid container spacing={3}>
              <Grid item xs={12}>
                <Typography variant="h6" gutterBottom>
                  Model Architecture
                </Typography>
                <Typography variant="body2" color="text.secondary" paragraph>
                  These settings control the AI model's complexity and capacity.
                </Typography>
              </Grid>

              <Grid item xs={12} md={6}>
                <Typography gutterBottom>
                  Hidden Dimension: {modelParams.hidden_dim}
                </Typography>
                <Slider
                  value={modelParams.hidden_dim || 128}
                  onChange={(e, v) => setModelParams({ ...modelParams, hidden_dim: v })}
                  min={16}
                  max={512}
                  step={16}
                  marks={[
                    { value: 64, label: '64 (Fast)' },
                    { value: 128, label: '128 (Balanced)' },
                    { value: 256, label: '256 (Powerful)' }
                  ]}
                />
                <Typography variant="caption" color="text.secondary">
                  Model complexity. Higher = more powerful but slower and more memory.
                </Typography>
              </Grid>

              <Grid item xs={12} md={6}>
                <Typography gutterBottom>
                  Number of Attention Heads: {modelParams.num_heads}
                </Typography>
                <Slider
                  value={modelParams.num_heads || 8}
                  onChange={(e, v) => setModelParams({ ...modelParams, num_heads: v })}
                  min={1}
                  max={16}
                  step={1}
                  marks={[
                    { value: 4, label: '4' },
                    { value: 8, label: '8' },
                    { value: 16, label: '16' }
                  ]}
                />
                <Typography variant="caption" color="text.secondary">
                  How many perspectives the model uses. More heads = better pattern recognition.
                </Typography>
              </Grid>

              <Grid item xs={12} md={6}>
                <Typography gutterBottom>
                  Number of Layers: {modelParams.num_layers}
                </Typography>
                <Slider
                  value={modelParams.num_layers || 3}
                  onChange={(e, v) => setModelParams({ ...modelParams, num_layers: v })}
                  min={1}
                  max={8}
                  step={1}
                  marks={[
                    { value: 2, label: '2 (Fast)' },
                    { value: 3, label: '3 (Balanced)' },
                    { value: 4, label: '4 (Deep)' }
                  ]}
                />
                <Typography variant="caption" color="text.secondary">
                  Model depth. More layers = better complex patterns but slower.
                </Typography>
              </Grid>

              <Grid item xs={12} md={6}>
                <TextField
                  label="Dropout Rate"
                  type="number"
                  fullWidth
                  value={modelParams.dropout || 0.3}
                  onChange={(e) => setModelParams({ ...modelParams, dropout: parseFloat(e.target.value) })}
                  inputProps={{ min: 0, max: 0.9, step: 0.1 }}
                  helperText="Prevents overfitting (0.0-0.9). Higher = more regularization."
                />
              </Grid>

              <Grid item xs={12} md={6}>
                <TextField
                  label="Learning Rate"
                  type="number"
                  fullWidth
                  value={modelParams.learning_rate || 0.001}
                  onChange={(e) => setModelParams({ ...modelParams, learning_rate: parseFloat(e.target.value) })}
                  inputProps={{ min: 0.00001, max: 0.1, step: 0.0001 }}
                  helperText="How fast the model learns (0.00001-0.1)."
                />
              </Grid>

              <Grid item xs={12}>
                <Button
                  variant="contained"
                  startIcon={<SaveIcon />}
                  onClick={() => updateModelMutation.mutate(modelParams)}
                  disabled={updateModelMutation.isLoading}
                >
                  Save Model Parameters
                </Button>
              </Grid>
            </Grid>
          </TabPanel>

          {/* Data Collection Tab */}
          <TabPanel value={activeTab} index={1}>
            <Grid container spacing={3}>
              <Grid item xs={12}>
                <Typography variant="h6" gutterBottom>
                  Data Collection Settings
                </Typography>
                <Typography variant="body2" color="text.secondary" paragraph>
                  Configure how data is collected from external sources.
                </Typography>
              </Grid>

              <Grid item xs={12} md={6}>
                <TextField
                  label="Look Back Window (days)"
                  type="number"
                  fullWidth
                  value={dataParams.look_back || 30}
                  onChange={(e) => setDataParams({ ...dataParams, look_back: parseInt(e.target.value) })}
                  inputProps={{ min: 1, max: 365 }}
                  helperText="How many days of history to use for predictions (1-365)."
                />
              </Grid>

              <Grid item xs={12} md={6}>
                <TextField
                  label="Correlation Threshold"
                  type="number"
                  fullWidth
                  value={dataParams.correlation_threshold || 0.5}
                  onChange={(e) => setDataParams({ ...dataParams, correlation_threshold: parseFloat(e.target.value) })}
                  inputProps={{ min: 0, max: 1, step: 0.1 }}
                  helperText="Minimum correlation between assets to include relationship (0.0-1.0)."
                />
              </Grid>

              <Grid item xs={12} md={6}>
                <TextField
                  label="API Rate Limit (seconds)"
                  type="number"
                  fullWidth
                  value={dataParams.api_rate_limit_seconds || 2.0}
                  onChange={(e) => setDataParams({ ...dataParams, api_rate_limit_seconds: parseFloat(e.target.value) })}
                  inputProps={{ min: 0.1, max: 60, step: 0.5 }}
                  helperText="Delay between API calls to avoid rate limits (0.1-60 seconds)."
                />
              </Grid>

              <Grid item xs={12}>
                <Button
                  variant="contained"
                  startIcon={<SaveIcon />}
                  onClick={() => updateDataMutation.mutate(dataParams)}
                  disabled={updateDataMutation.isLoading}
                >
                  Save Data Parameters
                </Button>
              </Grid>
            </Grid>
          </TabPanel>

          {/* Training Tab */}
          <TabPanel value={activeTab} index={2}>
            <Grid container spacing={3}>
              <Grid item xs={12}>
                <Typography variant="h6" gutterBottom>
                  Training Configuration
                </Typography>
                <Typography variant="body2" color="text.secondary" paragraph>
                  Control how the model is trained.
                </Typography>
              </Grid>

              <Grid item xs={12} md={6}>
                <Typography gutterBottom>
                  Batch Size: {trainingParams.batch_size}
                </Typography>
                <Slider
                  value={trainingParams.batch_size || 32}
                  onChange={(e, v) => setTrainingParams({ ...trainingParams, batch_size: v })}
                  min={4}
                  max={128}
                  step={4}
                  marks={[
                    { value: 8, label: '8 (Low Memory)' },
                    { value: 32, label: '32 (Balanced)' },
                    { value: 64, label: '64 (Fast)' }
                  ]}
                />
                <Typography variant="caption" color="text.secondary">
                  Examples processed at once. Higher = faster but more memory.
                </Typography>
              </Grid>

              <Grid item xs={12} md={6}>
                <TextField
                  label="Number of Epochs"
                  type="number"
                  fullWidth
                  value={trainingParams.num_epochs || 100}
                  onChange={(e) => setTrainingParams({ ...trainingParams, num_epochs: parseInt(e.target.value) })}
                  inputProps={{ min: 1, max: 1000 }}
                  helperText="Training iterations (1-1000). More epochs = better training but longer."
                />
              </Grid>

              <Grid item xs={12} md={6}>
                <TextField
                  label="Early Stopping Patience"
                  type="number"
                  fullWidth
                  value={trainingParams.early_stopping_patience || 10}
                  onChange={(e) => setTrainingParams({ ...trainingParams, early_stopping_patience: parseInt(e.target.value) })}
                  inputProps={{ min: 1, max: 100 }}
                  helperText="Stop if no improvement after N epochs (1-100)."
                />
              </Grid>

              <Grid item xs={12} md={6}>
                <TextField
                  label="Validation Split"
                  type="number"
                  fullWidth
                  value={trainingParams.validation_split || 0.2}
                  onChange={(e) => setTrainingParams({ ...trainingParams, validation_split: parseFloat(e.target.value) })}
                  inputProps={{ min: 0.1, max: 0.5, step: 0.05 }}
                  helperText="Portion of data for validation (0.1-0.5, typically 0.2)."
                />
              </Grid>

              <Grid item xs={12}>
                <Button
                  variant="contained"
                  startIcon={<SaveIcon />}
                  onClick={() => updateTrainingMutation.mutate(trainingParams)}
                  disabled={updateTrainingMutation.isLoading}
                >
                  Save Training Parameters
                </Button>
              </Grid>
            </Grid>
          </TabPanel>
        </CardContent>
      </Card>

      {config?.system_info && (
        <Card sx={{ mt: 2 }}>
          <CardContent>
            <Typography variant="h6" gutterBottom>
              System Information
            </Typography>
            <Grid container spacing={2}>
              <Grid item xs={6} md={3}>
                <Typography variant="body2" color="text.secondary">CPU Cores</Typography>
                <Typography variant="h6">{config.system_info.cpu_cores}</Typography>
              </Grid>
              <Grid item xs={6} md={3}>
                <Typography variant="body2" color="text.secondary">RAM</Typography>
                <Typography variant="h6">{config.system_info.memory_gb} GB</Typography>
              </Grid>
              <Grid item xs={6} md={3}>
                <Typography variant="body2" color="text.secondary">GPU Available</Typography>
                <Typography variant="h6">{config.system_info.gpu_available ? 'Yes' : 'No'}</Typography>
              </Grid>
              {config.system_info.gpu_available && (
                <Grid item xs={6} md={3}>
                  <Typography variant="body2" color="text.secondary">GPU Count</Typography>
                  <Typography variant="h6">{config.system_info.gpu_count}</Typography>
                </Grid>
              )}
            </Grid>
          </CardContent>
        </Card>
      )}
    </Box>
  )
}

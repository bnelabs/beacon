import { useEffect, useMemo, useState } from 'react'
import PageContainer from '../components/ui/PageContainer'
import Card, { CardHeader, CardTitle, CardContent, CardFooter } from '../components/ui/Card'
import Button from '../components/ui/Button'
import Badge from '../components/ui/Badge'
import LoadingSpinner from '../components/ui/LoadingSpinner'
import ErrorMessage from '../components/ui/ErrorMessage'
import { useModels, useModel } from '../hooks/useApi'
import { useRouter } from '../store/useRouter'

function ModelActionsMenu({ onEdit, onDuplicate, onDelete }) {
  const [open, setOpen] = useState(false)

  return (
    <div className="relative">
      <Button variant="ghost" size="sm" onClick={() => setOpen((prev) => !prev)}>
        <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 5v.01M12 12v.01M12 19v.01M12 6a1 1 0 110-2 1 1 0 010 2zm0 7a1 1 0 110-2 1 1 0 010 2zm0 7a1 1 0 110-2 1 1 0 010 2z" />
        </svg>
      </Button>
      {open && (
        <div className="absolute right-0 mt-2 w-40 rounded-xl border border-bne-frost bg-white shadow-bne-card z-20">
          <button className="w-full px-4 py-2 text-left text-sm hover:bg-bne-ice" onClick={() => { setOpen(false); onEdit?.() }}>Edit Metadata</button>
          <button className="w-full px-4 py-2 text-left text-sm hover:bg-bne-ice" onClick={() => { setOpen(false); onDuplicate?.() }}>Duplicate</button>
          <button className="w-full px-4 py-2 text-left text-sm text-bne-crimson hover:bg-bne-crimson/10" onClick={() => { setOpen(false); onDelete?.() }}>Delete</button>
        </div>
      )}
    </div>
  )
}

function TrainModelModal({ isOpen, onClose, model }) {
  if (!isOpen || !model) return null

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm">
      <Card className="w-full max-w-2xl max-h-[90vh] overflow-y-auto" as="div">
        <CardHeader className="flex items-center justify-between">
          <CardTitle>Train Model · {model.name}</CardTitle>
          <button onClick={onClose} className="p-2 hover:bg-bne-frost rounded-lg">
            <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div>
              <label className="block text-sm font-medium text-bne-ink mb-2">Training Job Name</label>
              <input type="text" defaultValue={`${model.name} Training`} className="w-full px-4 py-2 border border-bne-frost rounded-lg focus:outline-none focus:ring-2 focus:ring-bne-azure" />
            </div>
            <div>
              <label className="block text-sm font-medium text-bne-ink mb-2">Epochs</label>
              <input type="number" defaultValue={25} min={1} className="w-full px-4 py-2 border border-bne-frost rounded-lg focus:outline-none focus:ring-2 focus:ring-bne-azure" />
            </div>
          </div>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div>
              <label className="block text-sm font-medium text-bne-ink mb-2">Learning Rate</label>
              <input type="number" step="0.0001" defaultValue={0.001} className="w-full px-4 py-2 border border-bne-frost rounded-lg focus:outline-none focus:ring-2 focus:ring-bne-azure" />
            </div>
            <div>
              <label className="block text-sm font-medium text-bne-ink mb-2">Batch Size</label>
              <input type="number" defaultValue={32} className="w-full px-4 py-2 border border-bne-frost rounded-lg focus:outline-none focus:ring-2 focus:ring-bne-azure" />
            </div>
          </div>
          <div>
            <label className="block text-sm font-medium text-bne-ink mb-2">Notes</label>
            <textarea rows={3} className="w-full px-4 py-2 border border-bne-frost rounded-lg focus:outline-none focus:ring-2 focus:ring-bne-azure" placeholder="Describe training objective, dataset, or experiment notes." />
          </div>
        </CardContent>
        <CardFooter className="justify-end">
          <Button variant="ghost" onClick={onClose}>Cancel</Button>
          <Button variant="primary">Start Training</Button>
        </CardFooter>
      </Card>
    </div>
  )
}

function ModelDetailsDrawer({ model, onClose, onLaunch }) {
  const [scenarioName, setScenarioName] = useState('')
  const [horizonDays, setHorizonDays] = useState(30)
  const [adjustments, setAdjustments] = useState({})
  const [scenarioLoading, setScenarioLoading] = useState(false)
  const [scenarioError, setScenarioError] = useState(null)
  const [scenarioResult, setScenarioResult] = useState(null)

  useEffect(() => {
    if (!model) return
    setScenarioName('')
    setHorizonDays(30)
    setAdjustments({})
    setScenarioLoading(false)
    setScenarioError(null)
    setScenarioResult(null)
  }, [model?.model_id])

  if (!model) return null

  const availableSources = useMemo(() => {
    const perSource = model.result?.per_source_metrics
    if (perSource && typeof perSource === 'object') {
      return Object.keys(perSource)
    }
    const metrics = model.metrics || {}
    if (metrics.per_source_metrics && typeof metrics.per_source_metrics === 'object') {
      return Object.keys(metrics.per_source_metrics)
    }
    return []
  }, [model])

  const handleAdjustmentChange = (source, value) => {
    setAdjustments((prev) => ({ ...prev, [source]: value }))
  }

  const runScenario = async () => {
    const payload = {
      name: scenarioName || undefined,
      horizon_days: Number(horizonDays) || 30,
      adjustments: Object.entries(adjustments)
        .filter(([, val]) => typeof val === 'number' && Math.abs(val) > 0.01)
        .map(([source, val]) => ({ source, type: 'pct', value: Number(val) })),
    }

    if (!payload.adjustments.length) {
      setScenarioError('Adjust at least one data source to run a scenario.')
      return
    }

    setScenarioLoading(true)
    setScenarioError(null)
    try {
      const response = await fetch(`/api/models/${model.model_id}/simulate`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      })
      if (!response.ok) {
        const err = await response.json().catch(() => ({}))
        const message = err?.detail?.user_friendly || err?.detail || response.statusText
        throw new Error(message)
      }
      const data = await response.json()
      setScenarioResult(data)
    } catch (error) {
      setScenarioError(error.message || 'Failed to run scenario.')
    } finally {
      setScenarioLoading(false)
    }
  }

  return (
    <div className="fixed inset-0 z-40 flex justify-end">
      <div className="absolute inset-0 bg-black/30" onClick={onClose} />
      <Card className="relative z-50 w-full max-w-xl h-full overflow-y-auto shadow-2xl" as="div">
        <CardHeader className="flex items-center justify-between">
          <div>
            <CardTitle>{model.name}</CardTitle>
            <p className="text-sm text-bne-steel mt-1">{model.description || 'No description provided'}</p>
          </div>
          <button onClick={onClose} className="p-2 hover:bg-bne-frost rounded-lg">
            <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </CardHeader>
        <CardContent className="space-y-6">
          <section className="space-y-4">
            <h4 className="text-sm font-semibold text-bne-ink">Scenario Builder</h4>
            <p className="text-xs text-bne-steel">
              Adjust key data series to explore what-if outcomes without retraining. Positive values increase the series, negative values decrease it.
            </p>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <div>
                <label className="block text-xs font-medium text-bne-ink mb-1">Scenario Name</label>
                <input
                  type="text"
                  value={scenarioName}
                  onChange={(event) => setScenarioName(event.target.value)}
                  placeholder="e.g., Volatility +20%"
                  className="w-full px-3 py-2 border border-bne-frost rounded-lg focus:outline-none focus:ring-2 focus:ring-bne-azure"
                />
              </div>
              <div>
                <label className="block text-xs font-medium text-bne-ink mb-1">Horizon (days)</label>
                <select
                  value={horizonDays}
                  onChange={(event) => setHorizonDays(Number(event.target.value))}
                  className="w-full px-3 py-2 border border-bne-frost rounded-lg focus:outline-none focus:ring-2 focus:ring-bne-azure"
                >
                  {[7, 14, 30, 60, 90].map((value) => (
                    <option key={value} value={value}>{value} days</option>
                  ))}
                </select>
              </div>
            </div>

            {availableSources.length > 0 ? (
              <div className="space-y-4">
                {availableSources.map((source) => {
                  const value = adjustments[source] ?? 0
                  return (
                    <div key={source}>
                      <div className="flex items-center justify-between text-xs font-medium text-bne-ink mb-1">
                        <span>{source}</span>
                        <span className="text-bne-steel">{value > 0 ? '+' : ''}{value}%</span>
                      </div>
                      <input
                        type="range"
                        min={-50}
                        max={50}
                        step={1}
                        value={value}
                        onChange={(event) => handleAdjustmentChange(source, Number(event.target.value))}
                        className="w-full"
                      />
                    </div>
                  )
                })}
              </div>
            ) : (
              <p className="text-xs text-bne-steel">
                No per-source metrics available for this model. Scenario adjustments require identifiable source series.
              </p>
            )}

            {scenarioError && (
              <div className="rounded-lg border border-bne-crimson/30 bg-bne-crimson/10 px-3 py-2 text-xs text-bne-crimson">
                {scenarioError}
              </div>
            )}

            <div className="flex items-center justify-end gap-2">
              <Button variant="outline" size="sm" onClick={() => { setAdjustments({}); setScenarioResult(null); setScenarioError(null); }}>
                Reset
              </Button>
              <Button variant="primary" size="sm" onClick={runScenario} loading={scenarioLoading} disabled={!availableSources.length}>
                Run Scenario
              </Button>
            </div>

            {scenarioResult && (
              <div className="rounded-xl border border-bne-frost bg-bne-ice/40 p-4 space-y-3">
                <div className="flex items-center justify-between">
                  <div>
                    <p className="text-sm font-semibold text-bne-ink">{scenarioResult.name}</p>
                    <p className="text-xs text-bne-steel">
                      Avg risk score: {scenarioResult.summary?.avg_risk_score?.toFixed?.(4) ?? '0.0000'} · Sources: {scenarioResult.summary?.num_series ?? 0}
                    </p>
                  </div>
                  <Badge variant="primary" size="sm">Scenario</Badge>
                </div>
                <div className="max-h-48 overflow-y-auto rounded-lg border border-bne-frost">
                  <table className="min-w-full text-xs">
                    <thead className="bg-bne-ice/60 text-bne-steel uppercase">
                      <tr>
                        <th className="text-left px-3 py-2">Source</th>
                        <th className="text-left px-3 py-2">Prediction</th>
                        <th className="text-left px-3 py-2">Risk</th>
                      </tr>
                    </thead>
                    <tbody>
                      {scenarioResult.predictions.map((item) => (
                        <tr key={item.source} className="border-t border-bne-frost">
                          <td className="px-3 py-2 font-medium text-bne-ink">{item.source}</td>
                          <td className="px-3 py-2 font-mono text-bne-ink">{item.prediction?.toFixed?.(4) ?? '—'}</td>
                          <td className="px-3 py-2 font-mono text-bne-ink">{item.risk_score?.toFixed?.(4) ?? '—'}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            )}
          </section>
          <section>
            <h4 className="text-sm font-semibold text-bne-ink mb-2">Overview</h4>
            <div className="grid grid-cols-2 gap-4 text-sm">
              <div><span className="text-bne-steel">Status</span><p className="font-medium text-bne-ink">{model.status}</p></div>
              <div><span className="text-bne-steel">Architecture</span><p className="font-medium text-bne-ink">{model.architecture || 'LSTM'}</p></div>
              <div><span className="text-bne-steel">Input Features</span><p className="font-medium text-bne-ink">{model.input_features || '—'}</p></div>
              <div><span className="text-bne-steel">Prediction Steps</span><p className="font-medium text-bne-ink">{model.prediction_steps || '—'}</p></div>
              <div><span className="text-bne-steel">Last Trained</span><p className="font-medium text-bne-ink">{model.last_trained ? new Date(model.last_trained).toLocaleString() : 'Never'}</p></div>
              <div><span className="text-bne-steel">Accuracy</span><p className="font-medium text-bne-emerald">{model.accuracy ? `${model.accuracy}%` : '—'}</p></div>
            </div>
          </section>
          {model.hyperparameters && (
            <section>
              <h4 className="text-sm font-semibold text-bne-ink mb-2">Hyperparameters</h4>
              <pre className="bg-bne-ice/70 rounded-xl p-4 text-xs text-bne-ink font-mono overflow-auto">
                {JSON.stringify(model.hyperparameters, null, 2)}
              </pre>
            </section>
          )}
          {model.metrics && (
            <section>
              <h4 className="text-sm font-semibold text-bne-ink mb-2">Performance Metrics</h4>
              <pre className="bg-bne-ice/70 rounded-xl p-4 text-xs text-bne-ink font-mono overflow-auto">
                {JSON.stringify(model.metrics, null, 2)}
              </pre>
            </section>
          )}
          {model.data_summary && (
            <section>
              <h4 className="text-sm font-semibold text-bne-ink mb-2">Data Summary</h4>
              <pre className="bg-bne-ice/70 rounded-xl p-4 text-xs text-bne-ink font-mono overflow-auto">
                {JSON.stringify(model.data_summary, null, 2)}
              </pre>
            </section>
          )}
        </CardContent>
        <CardFooter className="justify-between">
          <Button variant="ghost" onClick={onClose}>Close</Button>
          <Button variant="primary" onClick={() => onLaunch?.(model, scenarioResult)}>
            Launch Explainability
          </Button>
        </CardFooter>
      </Card>
    </div>
  )
}

function ModelCard({ model, onTrain, onViewDetails, onShowMenu }) {
  const statusVariants = {
    ready: 'success',
    training: 'primary',
    failed: 'danger',
    draft: 'default'
  }

  return (
    <Card hover>
      <CardHeader>
        <div className="flex items-start justify-between">
          <div>
            <CardTitle>{model.name}</CardTitle>
            <p className="text-sm text-bne-steel mt-1">{model.description}</p>
          </div>
          <Badge variant={statusVariants[model.status] || 'default'}>
            {model.status}
          </Badge>
        </div>
      </CardHeader>

      <CardContent>
        <div className="space-y-3">
          <div className="flex items-center justify-between text-sm">
            <span className="text-bne-steel">Architecture</span>
            <span className="font-medium text-bne-ink">{model.architecture || 'LSTM'}</span>
          </div>
          <div className="flex items-center justify-between text-sm">
            <span className="text-bne-steel">Input Features</span>
            <span className="font-medium text-bne-ink">{model.input_features || 12}</span>
          </div>
          <div className="flex items-center justify-between text-sm">
            <span className="text-bne-steel">Prediction Steps</span>
            <span className="font-medium text-bne-ink">{model.prediction_steps || 4}</span>
          </div>
          {model.accuracy && (
            <div className="flex items-center justify-between text-sm">
              <span className="text-bne-steel">Accuracy</span>
              <span className="font-medium text-bne-emerald">{model.accuracy}%</span>
            </div>
          )}
          <div className="flex items-center justify-between text-sm">
            <span className="text-bne-steel">Last Trained</span>
            <span className="font-medium text-bne-ink">
              {model.last_trained ? new Date(model.last_trained).toLocaleDateString() : 'Never'}
            </span>
          </div>
        </div>
      </CardContent>

      <CardFooter>
        <Button variant="primary" size="sm" onClick={onTrain}>
          Train Model
        </Button>
        <Button variant="outline" size="sm" onClick={onViewDetails}>
          View Details
        </Button>
        <ModelActionsMenu
          onEdit={() => onShowMenu?.('edit', model)}
          onDuplicate={() => onShowMenu?.('duplicate', model)}
          onDelete={() => onShowMenu?.('delete', model)}
        />
      </CardFooter>
    </Card>
  )
}

function NewModelModal({ isOpen, onClose }) {
  if (!isOpen) return null

  return (
    <div className="fixed inset-0 bg-black/50 backdrop-blur-sm flex items-center justify-center z-50">
      <Card className="w-full max-w-2xl max-h-[90vh] overflow-y-auto">
        <CardHeader>
          <div className="flex items-center justify-between">
            <CardTitle>Create New Model</CardTitle>
            <button
              onClick={onClose}
              className="p-2 hover:bg-bne-frost rounded-lg transition-colors"
            >
              <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
              </svg>
            </button>
          </div>
        </CardHeader>

        <CardContent>
          <div className="space-y-4">
            <div>
              <label className="block text-sm font-medium text-bne-ink mb-2">
                Model Name
              </label>
              <input
                type="text"
                className="w-full px-4 py-2 border border-bne-frost rounded-lg focus:outline-none focus:ring-2 focus:ring-bne-azure"
                placeholder="e.g., FDIC Multi-Scale LSTM"
              />
            </div>

            <div>
              <label className="block text-sm font-medium text-bne-ink mb-2">
                Description
              </label>
              <textarea
                className="w-full px-4 py-2 border border-bne-frost rounded-lg focus:outline-none focus:ring-2 focus:ring-bne-azure"
                rows={3}
                placeholder="Describe your model..."
              />
            </div>

            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className="block text-sm font-medium text-bne-ink mb-2">
                  Architecture
                </label>
                <select className="w-full px-4 py-2 border border-bne-frost rounded-lg focus:outline-none focus:ring-2 focus:ring-bne-azure">
                  <option>LSTM</option>
                  <option>GRU</option>
                  <option>Transformer</option>
                </select>
              </div>

              <div>
                <label className="block text-sm font-medium text-bne-ink mb-2">
                  Input Features
                </label>
                <input
                  type="number"
                  className="w-full px-4 py-2 border border-bne-frost rounded-lg focus:outline-none focus:ring-2 focus:ring-bne-azure"
                  defaultValue={12}
                />
              </div>
            </div>

            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className="block text-sm font-medium text-bne-ink mb-2">
                  Sequence Length
                </label>
                <input
                  type="number"
                  className="w-full px-4 py-2 border border-bne-frost rounded-lg focus:outline-none focus:ring-2 focus:ring-bne-azure"
                  defaultValue={20}
                />
              </div>

              <div>
                <label className="block text-sm font-medium text-bne-ink mb-2">
                  Prediction Steps
                </label>
                <input
                  type="number"
                  className="w-full px-4 py-2 border border-bne-frost rounded-lg focus:outline-none focus:ring-2 focus:ring-bne-azure"
                  defaultValue={4}
                />
              </div>
            </div>

            <div>
              <label className="block text-sm font-medium text-bne-ink mb-2">
                Data Source
              </label>
              <select className="w-full px-4 py-2 border border-bne-frost rounded-lg focus:outline-none focus:ring-2 focus:ring-bne-azure">
                <option>FDIC</option>
                <option>ECB Banking</option>
                <option>FMP</option>
              </select>
            </div>
          </div>
        </CardContent>

        <CardFooter>
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button variant="primary">
            Create Model
          </Button>
        </CardFooter>
      </Card>
    </div>
  )
}

export default function Models() {
  const [showNewModel, setShowNewModel] = useState(false)
  const [filter, setFilter] = useState('all')
  const [selectedModelId, setSelectedModelId] = useState(null)
  const [trainModelId, setTrainModelId] = useState(null)
  const [menuAction, setMenuAction] = useState(null)
  const [consumedRouteSignature, setConsumedRouteSignature] = useState(null)
  const { data: models, isLoading, error, refetch } = useModels()
  const { data: modelDetails } = useModel(selectedModelId)
  const { data: trainTarget } = useModel(trainModelId)
  const navigate = useRouter((state) => state.navigate)
  const routerParams = useRouter((state) => state.params)

  const filteredModels = models?.filter(model => {
    if (filter === 'all') return true
    return model.status === filter
  }) || []

  useEffect(() => {
    if (!routerParams?.modelId) return
    const parsedModelId = typeof routerParams.modelId === 'number'
      ? routerParams.modelId
      : Number(routerParams.modelId)
    if (!Number.isFinite(parsedModelId)) return

    const signature = `${parsedModelId}:${routerParams?.ts ?? 'na'}:${routerParams?.intent ?? 'na'}`
    if (consumedRouteSignature === signature) return

    setConsumedRouteSignature(signature)
    setSelectedModelId(parsedModelId)
  }, [routerParams, consumedRouteSignature])

  if (isLoading) {
    return (
      <PageContainer title="Models">
        <div className="flex items-center justify-center h-64">
          <LoadingSpinner size="lg" message="Loading models..." />
        </div>
      </PageContainer>
    )
  }

  if (error) {
    return (
      <PageContainer title="Models">
        <ErrorMessage
          title="Failed to load models"
          error={error}
          onRetry={refetch}
        />
      </PageContainer>
    )
  }

  return (
    <>
      <PageContainer
        title="Models"
        actions={
          <Button variant="primary" onClick={() => setShowNewModel(true)}>
            <span className="flex items-center gap-2">
              <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M12 4v16m8-8H4" />
              </svg>
              New Model
            </span>
          </Button>
        }
      >
        <div className="space-y-6">
          <div className="flex items-center gap-2">
            <Button
              variant={filter === 'all' ? 'primary' : 'ghost'}
              size="sm"
              onClick={() => setFilter('all')}
            >
              All ({models?.length || 0})
            </Button>
            <Button
              variant={filter === 'ready' ? 'primary' : 'ghost'}
              size="sm"
              onClick={() => setFilter('ready')}
            >
              Ready ({models?.filter(m => m.status === 'ready').length || 0})
            </Button>
            <Button
              variant={filter === 'training' ? 'primary' : 'ghost'}
              size="sm"
              onClick={() => setFilter('training')}
            >
              Training ({models?.filter(m => m.status === 'training').length || 0})
            </Button>
            <Button
              variant={filter === 'draft' ? 'primary' : 'ghost'}
              size="sm"
              onClick={() => setFilter('draft')}
            >
              Draft ({models?.filter(m => m.status === 'draft').length || 0})
            </Button>
          </div>

          {filteredModels.length === 0 ? (
            <Card className="border-2 border-dashed border-bne-frost bg-bne-ice/50">
              <div className="text-center py-12">
                <svg
                  className="w-16 h-16 mx-auto text-bne-steel/50 mb-4"
                  fill="none"
                  viewBox="0 0 24 24"
                  stroke="currentColor"
                >
                  <path
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    strokeWidth={2}
                    d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z"
                  />
                </svg>
                <h3 className="text-lg font-semibold text-bne-ink mb-2">No models found</h3>
                <p className="text-sm text-bne-steel mb-4">
                  {filter === 'all'
                    ? 'Create your first model to get started'
                    : `No models with status "${filter}"`}
                </p>
                {filter === 'all' && (
                  <Button variant="primary" onClick={() => setShowNewModel(true)}>
                    Create Model
                  </Button>
                )}
              </div>
            </Card>
          ) : (
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
              {filteredModels.map((model) => (
                <ModelCard
                  key={model.model_id}
                  model={model}
                  onTrain={() => setTrainModelId(model.model_id)}
                  onViewDetails={() => setSelectedModelId(model.model_id)}
                  onShowMenu={(action) => setMenuAction({ action, model })}
                />
              ))}
            </div>
          )}
        </div>
      </PageContainer>

      <NewModelModal isOpen={showNewModel} onClose={() => setShowNewModel(false)} />
      <ModelDetailsDrawer
        model={modelDetails}
        onClose={() => setSelectedModelId(null)}
        onLaunch={(model, scenario) => {
          if (!model) return
          const modelId = model.model_id || model.id
          if (modelId) {
            navigate('results', {
              modelId,
              scenarioId: scenario?.scenario_id,
              scenarioName: scenario?.name,
            })
          }
          setSelectedModelId(null)
        }}
      />
      <TrainModelModal isOpen={!!trainModelId} onClose={() => setTrainModelId(null)} model={trainTarget} />
      {menuAction && (
        <div className="fixed inset-0 z-40 flex items-center justify-center bg-black/30">
          <Card className="w-full max-w-md">
            <CardHeader>
              <CardTitle>Action: {menuAction.action}</CardTitle>
            </CardHeader>
            <CardContent>
              <p className="text-sm text-bne-steel">
                Placeholder for {menuAction.action} action on model "{menuAction.model?.name}".
              </p>
            </CardContent>
            <CardFooter className="justify-end">
              <Button variant="ghost" onClick={() => setMenuAction(null)}>Close</Button>
            </CardFooter>
          </Card>
        </div>
      )}
    </>
  )
}

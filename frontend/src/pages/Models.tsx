import { useEffect, useMemo, useRef, useState } from 'react'
import { useFocusTrap } from '../hooks/useFocusTrap'
import PageContainer from '../components/ui/PageContainer'
import Card, { CardHeader, CardTitle, CardContent, CardFooter } from '../components/ui/Card'
import Button from '../components/ui/Button'
import Badge, { type BadgeVariant } from '../components/ui/Badge'
import LoadingSpinner from '../components/ui/LoadingSpinner'
import ErrorMessage from '../components/ui/ErrorMessage'
import { useModels, useModel } from '../hooks/useApi'
import { useRouter } from '../store/useRouter'
import JobCreationModal from '../components/jobs/JobCreationModal'
import type { EntityId, ModelDetailData, ModelSummary, ScenarioResult } from '../types/api'

interface TrainModelModalProps {
  isOpen: boolean
  onClose: () => void
  /** Hands off to the real training-job flow (JobCreationModal). */
  onContinue: () => void
  /** The summary row the button was clicked on — the detail endpoint has no
   *  `name`, so the title comes from the list. */
  model?: ModelSummary | null
}

function TrainModelModal({ isOpen, onClose, onContinue, model }: TrainModelModalProps) {
  if (!isOpen || !model) return null

  // This modal used to collect epochs/learning-rate/batch-size into inputs
  // that were never submitted — "Start Training" had no handler, and no
  // endpoint exists that trains a registered model in place. Training in
  // BEACON is a job: it needs a completed data-collection job to train on,
  // and it produces a new model rather than mutating this one. The button
  // now hands off to the real flow (JobCreationModal, training type)
  // instead of pretending.
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-bne-ink/40">
      <Card className="w-full max-w-2xl max-h-[90vh] overflow-y-auto" as="div">
        <CardHeader className="flex items-center justify-between">
          <CardTitle>Train Model · {model.name}</CardTitle>
          <button onClick={onClose} className="p-2 hover:bg-bne-paper-dim rounded-lg">
            <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </CardHeader>
        <CardContent className="space-y-4">
          <p className="text-sm leading-relaxed text-bne-muted">
            Training runs as a job: pick the completed data-collection job to
            train on, choose the architecture and hyperparameters, and the run
            registers a new model when it completes. Nothing is retrained
            in place — <span className="font-medium text-bne-ink">{model.name}</span> keeps
            its current weights and history either way.
          </p>
        </CardContent>
        <CardFooter className="justify-end">
          <Button variant="ghost" onClick={onClose}>Cancel</Button>
          <Button variant="primary" onClick={onContinue}>Start Training</Button>
        </CardFooter>
      </Card>
    </div>
  )
}

/** Architecture name from the training parameters' config block, falling
 *  back to the result blob's model_type — both are real outputs of the
 *  training pipeline. There is no `architecture` field on the wire; the old
 *  `'LSTM'` default asserted an architecture nobody reported. */
function drawerArchitecture(model: ModelDetailData): string {
  const config = model.parameters?.config as { model?: string | null } | undefined
  return config?.model || model.result?.model_type || '—'
}

interface ModelDetailsDrawerProps {
  model?: ModelDetailData | null
  /** The catalogue name for the header; ModelDetail does not carry one. */
  name?: string | null
  onClose: () => void
  onLaunch?: (model: ModelDetailData | null, scenario: ScenarioResult | null) => void
}

function ModelDetailsDrawer({ model, name, onClose, onLaunch }: ModelDetailsDrawerProps) {
  const drawerRef = useRef<HTMLDivElement>(null)
  // Above the early returns: the trap must engage and release in the same
  // order on every render, including the render where the drawer closes.
  useFocusTrap(drawerRef, Boolean(model), onClose)
  const [scenarioName, setScenarioName] = useState('')
  const [horizonDays, setHorizonDays] = useState(30)
  const [adjustments, setAdjustments] = useState<Record<string, number>>({})
  const [scenarioLoading, setScenarioLoading] = useState(false)
  const [scenarioError, setScenarioError] = useState<string | null>(null)
  const [scenarioResult, setScenarioResult] = useState<ScenarioResult | null>(null)

  const availableSources = useMemo<string[]>(() => {
    if (!model) {
      return []
    }
    // Per-source metrics live in the training job's `result` blob; the
    // detail's `metrics` object is the flat ModelMetrics extractor output
    // (mae/rmse/r2/accuracy/best_val_loss) and never carried them — the old
    // fallback read a field that does not exist.
    const perSource = model.result?.per_source_metrics
    if (perSource && typeof perSource === 'object') {
      return Object.keys(perSource)
    }
    return []
  }, [model])

  useEffect(() => {
    if (!model) return
    setScenarioName('')
    setHorizonDays(30)
    setAdjustments({})
    setScenarioLoading(false)
    setScenarioError(null)
    setScenarioResult(null)
    // The reset intentionally keys on the model id only: re-opening the same
    // model must not clobber an in-progress scenario session.
  }, [model?.model_id])

  if (!model) return null

  const handleAdjustmentChange = (source: string, value: number) => {
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
        const err = (await response.json().catch(() => ({}))) as {
          detail?: { user_friendly?: string } | string
        }
        const detail = err?.detail
        const message =
          (typeof detail === 'object' && detail !== null && detail.user_friendly) ||
          (typeof detail === 'string' && detail) ||
          response.statusText
        throw new Error(message)
      }
      const data = (await response.json()) as ScenarioResult
      setScenarioResult(data)
    } catch (error) {
      setScenarioError(error instanceof Error ? error.message : 'Failed to run scenario.')
    } finally {
      setScenarioLoading(false)
    }
  }

  return (
    <div ref={drawerRef} role="dialog" aria-modal="true" aria-label={name ?? `Model ${model.model_id}`} className="fixed inset-0 z-40 flex justify-end">
      <div className="absolute inset-0 bg-bne-ink/25" onClick={onClose} />
      <Card className="relative z-50 w-full max-w-xl h-full overflow-y-auto shadow-2xl" as="div">
        <CardHeader className="flex items-center justify-between">
          <div>
            <CardTitle>{name ?? `Model ${model.model_id}`}</CardTitle>
            {/* ModelDetail carries no description; showing "No description
                provided" for a field that cannot exist was inventing an
                absence. The model type is the real subtitle. */}
            <p className="text-sm text-bne-muted mt-1">{model.result?.model_type || 'Trained model'}</p>
          </div>
          <button onClick={onClose} className="p-2 hover:bg-bne-paper-dim rounded-lg">
            <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </CardHeader>
        <CardContent className="space-y-6">
          <section className="space-y-4">
            <h4 className="text-sm font-semibold text-bne-ink">Scenario Builder</h4>
            <p className="text-xs text-bne-muted">
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
                  className="w-full px-3 py-2 border border-bne-line rounded-lg focus:outline-none focus:ring-2 focus:ring-bne-pine"
                />
              </div>
              <div>
                <label className="block text-xs font-medium text-bne-ink mb-1">Horizon (days)</label>
                <select
                  value={horizonDays}
                  onChange={(event) => setHorizonDays(Number(event.target.value))}
                  className="w-full px-3 py-2 border border-bne-line rounded-lg focus:outline-none focus:ring-2 focus:ring-bne-pine"
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
                        <span className="text-bne-muted">{value > 0 ? '+' : ''}{value}%</span>
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
              <p className="text-xs text-bne-muted">
                No per-source metrics available for this model. Scenario adjustments require identifiable source series.
              </p>
            )}

            {scenarioError && (
              <div className="rounded-lg border border-bne-clay/30 bg-bne-clay/10 px-3 py-2 text-xs text-bne-clay">
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
              <div className="rounded-md border border-bne-line bg-bne-paper/40 p-4 space-y-3">
                <div className="flex items-center justify-between">
                  <div>
                    <p className="text-sm font-semibold text-bne-ink">{scenarioResult.name}</p>
                    <p className="text-xs text-bne-muted">
                      Avg risk score: {scenarioResult.summary?.avg_risk_score?.toFixed(4) ?? '0.0000'} · Sources: {scenarioResult.summary?.num_series ?? 0}
                    </p>
                  </div>
                  <Badge variant="primary" size="sm">Scenario</Badge>
                </div>
                <div className="max-h-48 overflow-y-auto rounded-lg border border-bne-line">
                  <table className="min-w-full text-xs">
                    <thead className="bg-bne-paper/60 text-bne-muted uppercase">
                      <tr>
                        <th className="text-left px-3 py-2">Source</th>
                        <th className="text-left px-3 py-2">Prediction</th>
                        <th className="text-left px-3 py-2">Risk</th>
                      </tr>
                    </thead>
                    <tbody>
                      {(scenarioResult.predictions ?? []).map((item) => (
                        <tr key={String(item.source)} className="border-t border-bne-line">
                          <td className="px-3 py-2 font-medium text-bne-ink">{item.source}</td>
                          <td className="px-3 py-2 font-mono text-bne-ink">{item.prediction?.toFixed(4) ?? '—'}</td>
                          <td className="px-3 py-2 font-mono text-bne-ink">{item.risk_score?.toFixed(4) ?? '—'}</td>
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
              <div><span className="text-bne-muted">Status</span><p className="font-medium text-bne-ink">{model.status}</p></div>
              <div><span className="text-bne-muted">Architecture</span><p className="font-medium text-bne-ink">{drawerArchitecture(model)}</p></div>
              <div><span className="text-bne-muted">Trained</span><p className="font-medium text-bne-ink">{(model.completed_at || model.created_at) ? new Date((model.completed_at || model.created_at) as string).toLocaleString() : '—'}</p></div>
              <div><span className="text-bne-muted">R²</span><p className="font-medium text-bne-moss">{model.metrics?.r2 != null ? model.metrics.r2.toFixed(4) : model.result?.test_r2 != null ? model.result.test_r2.toFixed(4) : '—'}</p></div>
              <div><span className="text-bne-muted">RMSE</span><p className="font-medium text-bne-ink">{model.metrics?.rmse != null ? model.metrics.rmse.toFixed(4) : model.result?.test_rmse != null ? model.result.test_rmse.toFixed(4) : '—'}</p></div>
              <div><span className="text-bne-muted">Data Job</span><p className="font-medium text-bne-ink">{model.data_job_id != null ? `#${model.data_job_id}` : '—'}</p></div>
            </div>
          </section>
          {model.parameters && (
            <section>
              {/* parameters IS the hyperparameter carrier: the training job's
                  config block (model, epochs, sequence_length, learning rate,
                  dropout) plus the data window it trained on. */}
              <h4 className="text-sm font-semibold text-bne-ink mb-2">Training Parameters</h4>
              <pre className="bg-bne-paper/70 rounded-md p-4 text-xs text-bne-ink font-mono overflow-auto">
                {JSON.stringify(model.parameters, null, 2)}
              </pre>
            </section>
          )}
          {model.metrics && (
            <section>
              <h4 className="text-sm font-semibold text-bne-ink mb-2">Performance Metrics</h4>
              <pre className="bg-bne-paper/70 rounded-md p-4 text-xs text-bne-ink font-mono overflow-auto">
                {JSON.stringify(model.metrics, null, 2)}
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

interface ModelCardProps {
  model: ModelSummary
  onTrain: () => void
  onViewDetails: () => void
}

function ModelCard({ model, onTrain, onViewDetails }: ModelCardProps) {
  const statusVariants: Record<string, BadgeVariant> = {
    completed: 'success',
    ready: 'success',
    training: 'primary',
    failed: 'danger',
    draft: 'default'
  }

  // Every row below reads a field ModelSummary actually carries. The card
  // used to render architecture/input_features/prediction_steps/accuracy/
  // last_trained — none of which the list endpoint sends — with invented
  // defaults ("LSTM", 12, 4) filling the gaps.
  return (
    <Card hover>
      <CardHeader>
        <div className="flex items-start justify-between">
          <div>
            <CardTitle>{model.name}</CardTitle>
            <p className="text-sm text-bne-muted mt-1">
              {model.model_type ? model.model_type : 'model'}
              {model.model_version ? ` · v${model.model_version}` : ''}
            </p>
          </div>
          <Badge variant={statusVariants[model.status ?? ''] || 'default'}>
            {model.status}
          </Badge>
        </div>
      </CardHeader>

      <CardContent>
        <div className="space-y-3">
          <div className="flex items-center justify-between text-sm">
            <span className="text-bne-muted">R²</span>
            <span className="font-medium text-bne-ink">{model.metrics?.r2 != null ? model.metrics.r2.toFixed(4) : '—'}</span>
          </div>
          <div className="flex items-center justify-between text-sm">
            <span className="text-bne-muted">RMSE</span>
            <span className="font-medium text-bne-ink">{model.metrics?.rmse != null ? model.metrics.rmse.toFixed(4) : '—'}</span>
          </div>
          {model.metrics?.accuracy != null && (
            <div className="flex items-center justify-between text-sm">
              <span className="text-bne-muted">Accuracy</span>
              <span className="font-medium text-bne-moss">{model.metrics.accuracy}</span>
            </div>
          )}
          <div className="flex items-center justify-between text-sm">
            <span className="text-bne-muted">Predictions</span>
            <span className="font-medium text-bne-ink">{model.predictions_available ? 'available' : 'none stored'}</span>
          </div>
          <div className="flex items-center justify-between text-sm">
            <span className="text-bne-muted">Created</span>
            <span className="font-medium text-bne-ink">
              {model.created_at ? new Date(model.created_at).toLocaleDateString() : '—'}
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
        {/* The card used to carry an Edit/Duplicate/Delete menu whose every
            entry opened a card reading "Placeholder for X action". No model
            update, copy or delete endpoint exists — a model is a training
            job's output — so the menu promised three operations the product
            cannot perform. It is gone. */}
      </CardFooter>
    </Card>
  )
}

interface NewModelModalProps {
  isOpen: boolean
  onClose: () => void
  /** Hands off to the real training-job flow (JobCreationModal). */
  onContinue: () => void
}

function NewModelModal({ isOpen, onClose, onContinue }: NewModelModalProps) {
  if (!isOpen) return null

  // The previous version of this modal was a form in name only: name,
  // architecture, sequence length and a "Create Model" button that had no
  // handler, because no POST /models endpoint exists — models are the
  // output of training jobs, never free-standing records. The modal now
  // says so and continues into the flow that actually creates one.
  return (
    <div className="fixed inset-0 bg-bne-ink/40 flex items-center justify-center z-50">
      <Card className="w-full max-w-2xl max-h-[90vh] overflow-y-auto">
        <CardHeader>
          <div className="flex items-center justify-between">
            <CardTitle>Create New Model</CardTitle>
            <button
              onClick={onClose}
              className="p-2 hover:bg-bne-paper-dim rounded-lg transition-colors"
            >
              <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
              </svg>
            </button>
          </div>
        </CardHeader>

        <CardContent>
          <p className="text-sm leading-relaxed text-bne-muted">
            Models are not free-standing records in BEACON — they are the
            output of training jobs. Creating one means choosing a completed
            data-collection job to train on, an architecture and its
            hyperparameters; the training run registers the model, its
            metrics and its lineage when it completes.
          </p>
        </CardContent>

        <CardFooter>
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button variant="primary" onClick={onContinue}>
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
  const [selectedModelId, setSelectedModelId] = useState<EntityId | null>(null)
  const [trainTarget, setTrainTarget] = useState<ModelSummary | null>(null)
  const [showTrainingJobModal, setShowTrainingJobModal] = useState(false)
  const [consumedRouteSignature, setConsumedRouteSignature] = useState<string | null>(null)
  const { data: models, isLoading, error, refetch } = useModels()
  const { data: modelDetails } = useModel(selectedModelId)
  const navigate = useRouter((state) => state.navigate)
  const routerParams = useRouter((state) => state.params)

  // The catalogue lists completed training jobs, so "Ready" is the completed
  // state — the button used to filter on a `ready` status the endpoint never
  // emits, which made three of the four filters permanently empty.
  const matchesFilter = (model: ModelSummary) => {
    if (filter === 'all') return true
    if (filter === 'ready') return model.status === 'completed'
    return model.status === filter
  }

  const filteredModels = models?.filter(matchesFilter) || []

  // The detail endpoint carries no name; the header takes it from the list row.
  const selectedSummary =
    selectedModelId != null
      ? models?.find((model) => String(model.model_id) === String(selectedModelId))
      : undefined

  useEffect(() => {
    if (!routerParams?.modelId) return
    const parsedModelId = Number(routerParams.modelId)
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
              Ready ({models?.filter((m) => m.status === 'completed').length || 0})
            </Button>
            <Button
              variant={filter === 'training' ? 'primary' : 'ghost'}
              size="sm"
              onClick={() => setFilter('training')}
            >
              Training ({models?.filter((m) => m.status === 'training').length || 0})
            </Button>
            <Button
              variant={filter === 'draft' ? 'primary' : 'ghost'}
              size="sm"
              onClick={() => setFilter('draft')}
            >
              Draft ({models?.filter((m) => m.status === 'draft').length || 0})
            </Button>
          </div>

          {filteredModels.length === 0 ? (
            <Card className="border-2 border-dashed border-bne-line bg-bne-paper/50">
              <div className="text-center py-12">
                <svg
                  className="w-16 h-16 mx-auto text-bne-muted/50 mb-4"
                  fill="none"
                  viewBox="0 0 24 24"
                  stroke="currentColor"
                  strokeWidth={2}
                >
                  <path
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z"
                  />
                </svg>
                <h3 className="text-lg font-semibold text-bne-ink mb-2">No models found</h3>
                <p className="text-sm text-bne-muted mb-4">
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
                  key={String(model.model_id)}
                  model={model}
                  onTrain={() => setTrainTarget(model)}
                  onViewDetails={() => setSelectedModelId(model.model_id)}
                />
              ))}
            </div>
          )}
        </div>
      </PageContainer>

      <NewModelModal
        isOpen={showNewModel}
        onClose={() => setShowNewModel(false)}
        onContinue={() => {
          setShowNewModel(false)
          setShowTrainingJobModal(true)
        }}
      />
      <ModelDetailsDrawer
        model={modelDetails}
        name={selectedSummary?.name}
        onClose={() => setSelectedModelId(null)}
        onLaunch={(model, scenario) => {
          if (!model) return
          navigate('results', {
            modelId: String(model.model_id),
            scenarioId: String(scenario?.scenario_id),
            scenarioName: String(scenario?.name),
          })
          setSelectedModelId(null)
        }}
      />
      <TrainModelModal
        isOpen={!!trainTarget}
        onClose={() => setTrainTarget(null)}
        onContinue={() => {
          setTrainTarget(null)
          setShowTrainingJobModal(true)
        }}
        model={trainTarget}
      />
      {/* The real creation flow both modals hand off to: a training job,
          which is the only thing in BEACON that produces a model. */}
      <JobCreationModal
        isOpen={showTrainingJobModal}
        onClose={() => setShowTrainingJobModal(false)}
        initialJobType="training"
      />
    </>
  )
}

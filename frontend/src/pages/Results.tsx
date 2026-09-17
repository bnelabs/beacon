import { useEffect, useMemo, useRef, useState } from 'react'
import PageContainer from '../components/ui/PageContainer'
import Card, { CardHeader, CardTitle, CardContent } from '../components/ui/Card'
import Button from '../components/ui/Button'
import Badge from '../components/ui/Badge'
import LoadingSpinner from '../components/ui/LoadingSpinner'
import ErrorMessage from '../components/ui/ErrorMessage'
import { useModel, useValidationReport } from '../hooks/useApi'
import { useRouter, type RouteParams } from '../store/useRouter'
import EmptyState from '../components/ui/EmptyState'
import type { ModelResultMetrics, PerSourceMetrics, ScenarioResult, ValidationSourceStats } from '../types/api'

/** The error `detail` FastAPI answers with: a plain string, or the typed
 *  {user_friendly, technical} envelope the backend raises on pipeline errors. */
type ApiErrorDetail = { detail?: { user_friendly?: string } | string }

function detailMessage(payload: ApiErrorDetail | null | undefined, fallback: string): string {
  const detail = payload?.detail
  if (typeof detail === 'object' && detail !== null && detail.user_friendly) {
    return detail.user_friendly
  }
  if (typeof detail === 'string' && detail) {
    return detail
  }
  return fallback
}

function formatNumber(value: unknown, digits = 4): string {
  if (value === null || value === undefined) return '—'
  const numeric = Number(value)
  if (!Number.isFinite(numeric)) return '—'
  return numeric.toFixed(digits)
}

function formatDate(value?: string | null): string {
  if (!value) return '—'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleString()
}

interface MetricCardProps {
  title: string
  value: string | number
  subtitle?: string
}

function MetricCard({ title, value, subtitle }: MetricCardProps) {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">{title}</CardTitle>
      </CardHeader>
      <CardContent>
        <p className="text-2xl font-semibold text-bne-ink">{value}</p>
        {subtitle && <p className="text-sm text-bne-muted mt-1">{subtitle}</p>}
      </CardContent>
    </Card>
  )
}

function ValidationReportCard({ jobId }: { jobId: string }) {
  const { data, isLoading } = useValidationReport(jobId)

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between">
          <CardTitle className="text-base">Predictive validity — job #{jobId}</CardTitle>
          {data?.status === 'validated' ? (
            <Badge variant="success" size="sm">validated</Badge>
          ) : (
            <Badge size="sm">not validated</Badge>
          )}
        </div>
      </CardHeader>
      <CardContent>
        {isLoading ? (
          <p className="text-sm text-bne-muted">Loading validation report…</p>
        ) : !data || data.status !== 'validated' ? (
          <EmptyState
            compact
            title="No predictive-validity statistics for this backtest"
            hint={data?.reason || 'Run the backtest with an event definition to measure precision, recall and lead time against declared stress events.'}
          />
        ) : (
          <div className="space-y-3">
            <p className="text-xs text-bne-muted">
              Event definition: {data.validation?.definition?.direction === 'down' ? 'falling' : 'rising'} moves
              above the {data.validation?.definition?.quantile} quantile of the {data.validation?.definition?.horizon}-step
              move, sustained {data.validation?.definition?.min_duration}+ steps.
              Mean ROC AUC across {data.validation?.sources_measured} source(s):{' '}
              <span className="bne-figure">{data.validation?.mean_roc_auc == null ? '—' : data.validation.mean_roc_auc.toFixed(3)}</span>
            </p>
            <div className="overflow-x-auto">
              <table className="w-full text-left text-[13px]">
                <thead>
                  <tr className="bne-micro">
                    <th className="py-1 pr-4">Source</th>
                    <th className="py-1 pr-4">ROC AUC</th>
                    <th className="py-1 pr-4">Avg precision</th>
                    <th className="py-1 pr-4">Events</th>
                    <th className="py-1 pr-4">Median lead</th>
                    <th className="py-1">Zero-lead</th>
                  </tr>
                </thead>
                <tbody className="text-bne-ink-soft">
                  {Object.entries(data.validation?.by_source || {}).map(([source, payload]: [string, ValidationSourceStats | null]) => (
                    <tr key={source} className="border-t border-bne-line-soft">
                      <td className="py-1.5 pr-4 font-mono text-xs">{source}</td>
                      {payload && payload.roc_auc != null ? (
                        <>
                          <td className="py-1.5 pr-4 tnum">{payload.roc_auc?.toFixed(3) ?? '—'}</td>
                          <td className="py-1.5 pr-4 tnum">{payload.average_precision?.toFixed(3) ?? '—'}</td>
                          <td className="py-1.5 pr-4 tnum">{payload.n_events ?? '—'}</td>
                          <td className="py-1.5 pr-4 tnum">{payload.lead_time?.median_lead ?? '—'}</td>
                          <td className="py-1.5 tnum">{payload.lead_time?.n_zero_lead ?? '—'}</td>
                        </>
                      ) : (
                        <td className="py-1.5 text-bne-faint" colSpan={5}>
                          {payload?.skipped || 'not measured'}
                        </td>
                      )}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  )
}

function ScenarioSummary({ scenario }: { scenario: ScenarioResult | null }) {
  if (!scenario) return null

  return (
    <Card>
      <CardHeader>
        <div className="flex items-start justify-between gap-3">
          <div>
            <CardTitle>{scenario.name}</CardTitle>
            <p className="text-sm text-bne-muted">
              Horizon {scenario.horizon_days} days · Created {formatDate(scenario.created_at)}
            </p>
          </div>
          <Badge variant="primary" size="sm">
            Scenario
          </Badge>
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4 text-sm text-bne-muted">
          <div>
            <p className="uppercase tracking-wide text-xs text-bne-muted/80 mb-1">Horizon</p>
            <p className="font-medium text-bne-ink">{scenario.horizon_days} days</p>
          </div>
          <div>
            <p className="uppercase tracking-wide text-xs text-bne-muted/80 mb-1">Series Simulated</p>
            <p className="font-medium text-bne-ink">
              {scenario.summary?.num_series ?? scenario.predictions?.length ?? '—'}
            </p>
          </div>
          <div>
            <p className="uppercase tracking-wide text-xs text-bne-muted/80 mb-1">Storage Path</p>
            <p className="font-medium text-bne-ink truncate">{scenario.storage_path || '—'}</p>
          </div>
        </div>

        {Array.isArray(scenario.adjustments) && scenario.adjustments.length > 0 && (
          <div className="overflow-x-auto rounded-lg border border-bne-line">
            <table className="min-w-full text-sm">
              <thead className="bg-bne-paper/60 text-bne-muted uppercase text-xs">
                <tr>
                  <th className="text-left px-3 py-2">Source</th>
                  <th className="text-left px-3 py-2">Type</th>
                  <th className="text-left px-3 py-2">Adjustment</th>
                </tr>
              </thead>
              <tbody>
                {scenario.adjustments.map((adjustment, index) => (
                  <tr key={`${adjustment.source}-${adjustment.type}-${index}`} className="border-t border-bne-line">
                    <td className="px-3 py-2 font-medium text-bne-ink">{adjustment.source}</td>
                    <td className="px-3 py-2 text-bne-muted uppercase text-xs">{adjustment.type}</td>
                    <td className="px-3 py-2 font-mono text-bne-ink">
                      {formatNumber(adjustment.value, adjustment.type === 'pct' ? 2 : 4)}
                      {adjustment.type === 'pct' ? '%' : ''}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </CardContent>
    </Card>
  )
}

interface PredictionRow {
  key?: string | number
  label: string
  prediction?: number | null
  risk?: number | null
  confidence?: { lower?: number | null; upper?: number | null } | null
  explanation?: string | null
  uncertaintyStatus?: string | null
  uncertaintyReasons?: string | null
  epistemicShare?: number | null
}

/* A refused prediction is absence, and the table must show it as absence:
 * the numbers render as em-dashes (formatNumber maps null/NaN to '—') and
 * this cell says why, in the clay end of the risk palette. Nothing here may
 * render a refused score as a number. */
function UncertaintyCell({ row }: { row: PredictionRow }) {
  if (row.uncertaintyStatus === 'refused') {
    return (
      <span className="inline-flex items-center gap-2 max-w-[22rem]">
        <span
          className="shrink-0 rounded bg-bne-clay/15 px-2 py-0.5 text-xs font-semibold uppercase tracking-wide text-bne-clay"
          title={row.uncertaintyReasons ?? 'prediction refused by the uncertainty assessment'}
        >
          Refused
        </span>
        {row.uncertaintyReasons ? (
          <span className="text-xs text-bne-muted truncate" title={row.uncertaintyReasons}>
            {row.uncertaintyReasons}
          </span>
        ) : null}
      </span>
    )
  }
  if (row.uncertaintyStatus === 'assessed') {
    const share = row.epistemicShare
    return (
      <span
        className="font-mono text-xs text-bne-muted"
        title="share of predictive variance that is model ignorance (deep-ensemble decomposition); the rest is world noise"
      >
        {typeof share === 'number' && Number.isFinite(share)
          ? `epistemic ${(share * 100).toFixed(0)}%`
          : 'assessed'}
      </span>
    )
  }
  if (row.uncertaintyStatus === 'not_measurable_single_model') {
    return (
      <span
        className="text-xs text-bne-muted"
        title="single frozen checkpoint: the aleatoric/epistemic split needs independently trained ensemble members"
      >
        not measurable
      </span>
    )
  }
  return <span className="text-xs text-bne-muted">—</span>
}

function PredictionsTable({ rows }: { rows: PredictionRow[] }) {
  if (!rows.length) {
    return <p className="text-sm text-bne-muted">No prediction outputs available yet.</p>
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-bne-line bg-bne-paper/40">
            <th className="text-left py-3 px-4 font-semibold text-bne-ink">Series</th>
            <th className="text-left py-3 px-4 font-semibold text-bne-ink">Prediction</th>
            <th className="text-left py-3 px-4 font-semibold text-bne-ink">Risk Score</th>
            <th className="text-left py-3 px-4 font-semibold text-bne-ink">Confidence</th>
            <th className="text-left py-3 px-4 font-semibold text-bne-ink">Uncertainty</th>
            <th className="text-left py-3 px-4 font-semibold text-bne-ink">Insight</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row, index) => (
            <tr key={row.key ?? index} className="border-b border-bne-line last:border-0 hover:bg-bne-paper/30 transition-colors">
              <td className="py-3 px-4 font-medium text-bne-ink">{row.label}</td>
              <td className="py-3 px-4 font-mono text-bne-ink">{formatNumber(row.prediction)}</td>
              <td className="py-3 px-4 font-mono text-bne-ink">{formatNumber(row.risk)}</td>
              <td className="py-3 px-4 font-mono text-bne-muted">
                {row.confidence
                  ? `${formatNumber(row.confidence.lower)} – ${formatNumber(row.confidence.upper)}`
                  : '—'}
              </td>
              <td className="py-3 px-4"><UncertaintyCell row={row} /></td>
              <td className="py-3 px-4 text-sm text-bne-muted">{row.explanation || '—'}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

export interface ResultsProps {
  params?: RouteParams
}

export default function Results({ params = {} }: ResultsProps) {
  const navigate = useRouter((state) => state.navigate)

  const rawModelId = params?.modelId
  const parsedModelId = typeof rawModelId === 'number' ? rawModelId : Number(rawModelId)
  const modelId = Number.isFinite(parsedModelId) ? parsedModelId : undefined
  const scenarioId = params?.scenarioId
  const scenarioNameFromParams = params?.scenarioName

  const {
    data: modelDetail,
    isLoading: modelLoading,
    error: modelError,
    refetch: refetchModel
  } = useModel(modelId)

  const [scenario, setScenario] = useState<ScenarioResult | null>(null)
  const validationJobId = params?.jobId
  const [scenarioLoading, setScenarioLoading] = useState(false)
  const [scenarioError, setScenarioError] = useState<string | null>(null)
  const [scenarioReloadKey, setScenarioReloadKey] = useState(0)
  const [builderName, setBuilderName] = useState('')
  const [builderHorizon, setBuilderHorizon] = useState(30)
  const [builderAdjustments, setBuilderAdjustments] = useState<Record<string, number>>({})
  const [builderError, setBuilderError] = useState<string | null>(null)
  const [builderLoading, setBuilderLoading] = useState(false)
  const builderRef = useRef<HTMLElement>(null)

  const baselineMetrics: ModelResultMetrics = modelDetail?.result || {}
  const perSourceMetrics: Record<string, PerSourceMetrics> = baselineMetrics?.per_source_metrics || {}
  const availableSources = useMemo(() => Object.keys(perSourceMetrics), [perSourceMetrics])

  useEffect(() => {
    if (!modelId || !scenarioId) {
      setScenario(null)
      setScenarioLoading(false)
      setScenarioError(null)
      return
    }

    let cancelled = false
    const load = async () => {
      setScenarioLoading(true)
      setScenarioError(null)

      try {
        const response = await fetch(`/api/models/${modelId}/scenarios/${scenarioId}`)
        if (!response.ok) {
          const payload = (await response.json().catch(() => ({}))) as ApiErrorDetail
          const message = detailMessage(payload, response.statusText || 'Failed to load scenario results.')
          throw new Error(message)
        }
        const data = (await response.json()) as ScenarioResult
        if (!cancelled) {
          setScenario(data)
        }
      } catch (error) {
        if (!cancelled) {
          setScenario(null)
          setScenarioError(
            error instanceof Error ? error.message : 'Failed to load scenario results.'
          )
        }
      } finally {
        if (!cancelled) {
          setScenarioLoading(false)
        }
      }
    }

    load()
    return () => {
      cancelled = true
    }
  }, [modelId, scenarioId, scenarioReloadKey])

  useEffect(() => {
    const template: Record<string, number> = {}
    availableSources.forEach((source) => {
      template[source] = 0
    })
    setBuilderAdjustments(template)
  }, [availableSources])

  if (!modelId) {
    return (
      <PageContainer
        title="Results"
        actions={
          <Button variant="primary" size="sm" onClick={() => navigate('models')}>
            Back to Models
          </Button>
        }
      >
        <ErrorMessage
          title="Select a model to view results"
          message="Open any trained model from the Models page to access predictions and scenarios."
        />
      </PageContainer>
    )
  }

  if (modelLoading || scenarioLoading) {
    const title =
      scenarioNameFromParams || scenario?.name || modelDetail?.result?.model_type || `Model ${modelId} Results`

    return (
      <PageContainer title={title}>
        <div className="flex items-center justify-center h-64">
          <LoadingSpinner size="lg" message="Loading model results…" />
        </div>
      </PageContainer>
    )
  }

  if (modelError) {
    return (
      <PageContainer title="Results">
        <ErrorMessage
          title="Failed to load model detail"
          error={modelError}
          onRetry={refetchModel}
        />
      </PageContainer>
    )
  }

  const summaryCards: MetricCardProps[] = (() => {
    if (scenario?.summary) {
      return [
        {
          title: 'Average Risk Score',
          value: formatNumber(scenario.summary.avg_risk_score),
          subtitle: 'Scenario-wide average risk score'
        },
        {
          title: 'Maximum Risk Score',
          value: formatNumber(scenario.summary.max_risk_score),
          subtitle: 'Highest observed risk within adjusted series'
        },
        {
          title: 'Minimum Risk Score',
          value: formatNumber(scenario.summary.min_risk_score),
          subtitle: 'Lowest observed risk within adjusted series'
        },
        {
          title: 'Series Simulated',
          value: scenario.summary.num_series ?? scenario.predictions?.length ?? '—',
          subtitle: 'Total data series included in the scenario'
        }
      ]
    }

    const cards: MetricCardProps[] = []
    if (baselineMetrics.test_rmse ?? baselineMetrics.rmse) {
      cards.push({
        title: 'Test RMSE',
        value: formatNumber(baselineMetrics.test_rmse ?? baselineMetrics.rmse),
        subtitle: 'Root mean squared error on evaluation set'
      })
    }
    if (baselineMetrics.test_mae ?? baselineMetrics.mae) {
      cards.push({
        title: 'Test MAE',
        value: formatNumber(baselineMetrics.test_mae ?? baselineMetrics.mae),
        subtitle: 'Mean absolute error across forecasts'
      })
    }
    if (baselineMetrics.test_r2 ?? baselineMetrics.r2) {
      cards.push({
        title: 'R² Score',
        value: formatNumber(baselineMetrics.test_r2 ?? baselineMetrics.r2),
        subtitle: 'Coefficient of determination'
      })
    }
    if (baselineMetrics.accuracy !== undefined) {
      cards.push({
        title: 'Accuracy',
        value: `${formatNumber(baselineMetrics.accuracy, 2)}%`,
        subtitle: 'Reported classification accuracy'
      })
    }
    if (!cards.length) {
      cards.push({
        title: 'Model Status',
        value: modelDetail?.status || 'Unknown',
        subtitle: 'No evaluation metrics were reported'
      })
    }
    return cards
  })()

  const predictionsRows: PredictionRow[] = (() => {
    if (Array.isArray(scenario?.predictions) && scenario?.predictions?.length) {
      return scenario.predictions.map((item, index) => ({
        key: item.source ?? item.bank_id ?? index,
        label: item.source || item.bank_name || `Series ${index + 1}`,
        prediction: item.prediction ?? item.overall_risk,
        risk: item.risk_score ?? item.overall_risk,
        confidence:
          // nullish, not just undefined: a refused row carries explicit
          // nulls, and 'null – null' would render where a dash belongs.
          item.confidence_lower != null && item.confidence_upper != null
            ? { lower: item.confidence_lower, upper: item.confidence_upper }
            : null,
        explanation: item.explanation,
        uncertaintyStatus: item.uncertainty_status,
        uncertaintyReasons: item.uncertainty_reasons,
        epistemicShare: item.epistemic_share
      }))
    }

    return Object.entries(perSourceMetrics).map(([source, entry]) => ({
      key: source,
      label: source,
      prediction: entry.prediction ?? entry.forecast ?? entry.rmse ?? entry.mae,
      risk: entry.risk_score ?? entry.rmse ?? entry.mae ?? entry.r2,
      confidence:
        entry.confidence_lower !== undefined && entry.confidence_upper !== undefined
          ? { lower: entry.confidence_lower, upper: entry.confidence_upper }
          : null,
      explanation: entry.explanation,
      // PerSourceMetrics carries an unknown-valued index signature; these
      // keys are the engine's row fields when the payload came from a
      // post-wiring prediction job, and absent otherwise.
      uncertaintyStatus: entry.uncertainty_status as string | null | undefined,
      uncertaintyReasons: entry.uncertainty_reasons as string | null | undefined,
      epistemicShare: entry.epistemic_share as number | null | undefined
    }))
  })()

  const featureDrivers = (() => {
    if (scenario?.feature_importances) {
      return Object.entries(scenario.feature_importances)
        .map(([name, value]) => ({
          name,
          value: Number(value) || 0
        }))
        .sort((a, b) => Math.abs(b.value) - Math.abs(a.value))
        .slice(0, 8)
    }

    return predictionsRows
      .map((row) => ({
        name: row.label,
        value: Number(row.risk) || 0
      }))
      .sort((a, b) => Math.abs(b.value) - Math.abs(a.value))
      .slice(0, 8)
  })()

  const modelInfoRows: Array<{ label: string; value: string | number }> = [
    { label: 'Model ID', value: modelDetail?.model_id ?? modelId },
    { label: 'Status', value: modelDetail?.status },
    { label: 'Model Type', value: baselineMetrics?.model_type || baselineMetrics?.config?.model_type },
    { label: 'Version', value: baselineMetrics?.model_version },
    { label: 'Created', value: formatDate(modelDetail?.created_at) },
    { label: 'Completed', value: formatDate(modelDetail?.completed_at) },
    { label: 'Data Job', value: modelDetail?.data_job_id ? `Job ${modelDetail.data_job_id}` : null },
    { label: 'Predictions Path', value: modelDetail?.predictions_path }
  ].filter(
    (item): item is { label: string; value: string | number } =>
      item.value !== undefined && item.value !== null && item.value !== ''
  )

  const pageTitle =
    scenario?.name ||
    scenarioNameFromParams ||
    baselineMetrics?.model_type ||
    `Model ${modelId} Results`

  const runScenario = async () => {
    if (!modelId) return
    const adjustments = Object.entries(builderAdjustments)
      .filter(([, value]) => Math.abs(Number(value)) > 0.01)
      .map(([source, value]) => ({
        source,
        type: 'pct',
        value: Number(value)
      }))

    if (!adjustments.length) {
      setBuilderError('Adjust at least one data source to run a scenario.')
      return
    }

    setBuilderError(null)
    setBuilderLoading(true)
    try {
      const response = await fetch(`/api/models/${modelId}/simulate`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          name: builderName || undefined,
          horizon_days: Number(builderHorizon) || 30,
          adjustments
        })
      })
      if (!response.ok) {
        const payload = (await response.json().catch(() => ({}))) as ApiErrorDetail
        const message = detailMessage(payload, response.statusText || 'Scenario simulation failed.')
        throw new Error(message)
      }
      const data = (await response.json()) as ScenarioResult
      setScenario(data)
      setBuilderName(data.name ?? '')
    } catch (error) {
      setBuilderError(error instanceof Error ? error.message : 'Scenario simulation failed.')
    } finally {
      setBuilderLoading(false)
    }
  }

  const resetAdjustments = () => {
    const template: Record<string, number> = {}
    availableSources.forEach((source) => {
      template[source] = 0
    })
    setBuilderAdjustments(template)
    setBuilderError(null)
  }

  return (
    <PageContainer
      title={pageTitle}
      actions={
        <div className="flex items-center gap-2">
          <Button variant="outline" size="sm" onClick={() => navigate('models', { modelId: String(modelId) })}>
            Back to Models
          </Button>
          <Button
            variant="primary"
            size="sm"
            onClick={() => builderRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' })}
            disabled={!availableSources.length}
          >
            Build Scenario
          </Button>
        </div>
      }
    >
      <div className="space-y-6">
        {validationJobId && <ValidationReportCard jobId={validationJobId} />}
        {scenarioError && (
          <ErrorMessage
            title="Unable to load scenario"
            message={scenarioError}
            onRetry={() => {
              if (!modelId || !scenarioId) return
              setScenarioReloadKey((value) => value + 1)
            }}
          />
        )}

        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
          {summaryCards.map((card, index) => (
            <MetricCard
              key={`${card.title}-${index}`}
              title={card.title}
              value={card.value}
              subtitle={card.subtitle}
            />
          ))}
        </div>

        <Card ref={builderRef}>
          <CardHeader>
            <CardTitle>Scenario Builder</CardTitle>
          </CardHeader>
          <CardContent className="space-y-6">
            {!availableSources.length ? (
              <p className="text-sm text-bne-muted">
                This model does not expose per-source metrics yet. Run a multi-source training job to unlock scenario simulations.
              </p>
            ) : (
              <>
                <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                  <div>
                    <label className="block text-xs font-medium text-bne-ink mb-1">Scenario Name</label>
                    <input
                      type="text"
                      value={builderName}
                      onChange={(event) => setBuilderName(event.target.value)}
                      className="w-full px-3 py-2 border border-bne-line rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-bne-pine"
                      placeholder="e.g., Volatility +20%"
                    />
                  </div>
                  <div>
                    <label className="block text-xs font-medium text-bne-ink mb-1">Horizon (days)</label>
                    <select
                      value={builderHorizon}
                      onChange={(event) => setBuilderHorizon(Number(event.target.value))}
                      className="w-full px-3 py-2 border border-bne-line rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-bne-pine"
                    >
                      {[7, 14, 30, 60, 90].map((value) => (
                        <option key={value} value={value}>
                          {value} days
                        </option>
                      ))}
                    </select>
                  </div>
                  <div className="rounded-lg border border-bne-line bg-bne-paper/60 p-3 text-xs text-bne-muted">
                    Positive values simulate growth; negative values stress-test declines.
                  </div>
                </div>

                <div className="space-y-4">
                  {availableSources.map((source) => {
                    const value = builderAdjustments[source] ?? 0
                    const formatted = value > 0 ? `+${value}` : value
                    return (
                      <div key={source}>
                        <div className="flex items-center justify-between text-xs font-medium text-bne-ink mb-1">
                          <span>{source}</span>
                          <span className="text-bne-muted">{formatted}%</span>
                        </div>
                        <input
                          type="range"
                          min={-50}
                          max={50}
                          step={1}
                          value={value}
                          onChange={(event) =>
                            setBuilderAdjustments((prev) => ({
                              ...prev,
                              [source]: Number(event.target.value)
                            }))
                          }
                          className="w-full"
                        />
                      </div>
                    )
                  })}
                </div>

                {builderError && (
                  <div className="rounded-lg border border-bne-clay/30 bg-bne-clay/10 px-3 py-2 text-xs text-bne-clay">
                    {builderError}
                  </div>
                )}

                <div className="flex items-center justify-end gap-2">
                  <Button variant="outline" size="sm" onClick={resetAdjustments} disabled={builderLoading}>
                    Reset
                  </Button>
                  <Button variant="primary" size="sm" onClick={runScenario} loading={builderLoading}>
                    Run Scenario
                  </Button>
                </div>
              </>
            )}
          </CardContent>
        </Card>

        {scenario && <ScenarioSummary scenario={scenario} />}

        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          <Card className="lg:col-span-2">
            <CardHeader>
              <div className="flex items-center justify-between">
                <CardTitle>{scenario ? 'Scenario Predictions' : 'Baseline Predictions'}</CardTitle>
                {scenario && <Badge variant="primary" size="sm">What-if</Badge>}
              </div>
            </CardHeader>
            <CardContent>
              <PredictionsTable rows={predictionsRows} />
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>{scenario ? 'Scenario Drivers' : 'Top Risk Drivers'}</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="space-y-3">
                {featureDrivers.map((item) => (
                  <div key={item.name} className="space-y-1">
                    <div className="flex items-center justify-between text-sm">
                      <span className="text-bne-muted">{item.name}</span>
                      <span className="font-medium text-bne-ink">{formatNumber(item.value)}</span>
                    </div>
                    <div className="w-full h-2 bg-bne-paper-dim rounded-full overflow-hidden">
                      <div
                        className="h-full bg-bne-pine transition-all duration-300"
                        style={{ width: `${Math.min(Math.abs(item.value) * 100, 100)}%` }}
                      />
                    </div>
                  </div>
                ))}
                {!featureDrivers.length && (
                  <p className="text-sm text-bne-muted">No drivers available.</p>
                )}
              </div>
            </CardContent>
          </Card>
        </div>

        <Card>
          <CardHeader>
            <CardTitle>Model Metadata</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="space-y-3 text-sm">
              {modelInfoRows.map((row) => (
                <div key={row.label}>
                  <p className="text-bne-muted">{row.label}</p>
                  <p className="font-medium text-bne-ink break-words">{row.value}</p>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>

        {scenario?.executive_summary && (
          <Card>
            <CardHeader>
              <CardTitle>Scenario Executive Summary</CardTitle>
            </CardHeader>
            <CardContent>
              <p className="whitespace-pre-line text-sm leading-relaxed text-bne-ink">
                {scenario.executive_summary}
              </p>
            </CardContent>
          </Card>
        )}

        {!scenario?.executive_summary && baselineMetrics?.executive_summary && (
          <Card>
            <CardHeader>
              <CardTitle>Executive Summary</CardTitle>
            </CardHeader>
            <CardContent>
              <p className="whitespace-pre-line text-sm leading-relaxed text-bne-ink">
                {baselineMetrics.executive_summary}
              </p>
            </CardContent>
          </Card>
        )}
      </div>
    </PageContainer>
  )
}

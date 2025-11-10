import { useEffect, useMemo, useRef, useState } from 'react'
import PageContainer from '../components/ui/PageContainer'
import Card, { CardHeader, CardTitle, CardContent } from '../components/ui/Card'
import Button from '../components/ui/Button'
import Badge from '../components/ui/Badge'
import LoadingSpinner from '../components/ui/LoadingSpinner'
import ErrorMessage from '../components/ui/ErrorMessage'
import { useModel } from '../hooks/useApi'
import { useRouter } from '../store/useRouter'

function formatNumber(value, digits = 4) {
  if (value === null || value === undefined) return '—'
  const numeric = Number(value)
  if (!Number.isFinite(numeric)) return '—'
  return numeric.toFixed(digits)
}

function formatDate(value) {
  if (!value) return '—'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleString()
}

function MetricCard({ title, value, subtitle }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">{title}</CardTitle>
      </CardHeader>
      <CardContent>
        <p className="text-2xl font-semibold text-bne-ink">{value}</p>
        {subtitle && <p className="text-sm text-bne-steel mt-1">{subtitle}</p>}
      </CardContent>
    </Card>
  )
}

function ScenarioSummary({ scenario }) {
  if (!scenario) return null

  return (
    <Card>
      <CardHeader>
        <div className="flex items-start justify-between gap-3">
          <div>
            <CardTitle>{scenario.name}</CardTitle>
            <p className="text-sm text-bne-steel">
              Horizon {scenario.horizon_days} days · Created {formatDate(scenario.created_at)}
            </p>
          </div>
          <Badge variant="primary" size="sm">
            Scenario
          </Badge>
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4 text-sm text-bne-steel">
          <div>
            <p className="uppercase tracking-wide text-xs text-bne-steel/80 mb-1">Horizon</p>
            <p className="font-medium text-bne-ink">{scenario.horizon_days} days</p>
          </div>
          <div>
            <p className="uppercase tracking-wide text-xs text-bne-steel/80 mb-1">Series Simulated</p>
            <p className="font-medium text-bne-ink">
              {scenario.summary?.num_series ?? scenario.predictions?.length ?? '—'}
            </p>
          </div>
          <div>
            <p className="uppercase tracking-wide text-xs text-bne-steel/80 mb-1">Storage Path</p>
            <p className="font-medium text-bne-ink truncate">{scenario.storage_path || '—'}</p>
          </div>
        </div>

        {Array.isArray(scenario.adjustments) && scenario.adjustments.length > 0 && (
          <div className="overflow-x-auto rounded-lg border border-bne-frost">
            <table className="min-w-full text-sm">
              <thead className="bg-bne-ice/60 text-bne-steel uppercase text-xs">
                <tr>
                  <th className="text-left px-3 py-2">Source</th>
                  <th className="text-left px-3 py-2">Type</th>
                  <th className="text-left px-3 py-2">Adjustment</th>
                </tr>
              </thead>
              <tbody>
                {scenario.adjustments.map((adjustment, index) => (
                  <tr key={`${adjustment.source}-${adjustment.type}-${index}`} className="border-t border-bne-frost">
                    <td className="px-3 py-2 font-medium text-bne-ink">{adjustment.source}</td>
                    <td className="px-3 py-2 text-bne-steel uppercase text-xs">{adjustment.type}</td>
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

function PredictionsTable({ rows }) {
  if (!rows.length) {
    return <p className="text-sm text-bne-steel">No prediction outputs available yet.</p>
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-bne-frost bg-bne-ice/40">
            <th className="text-left py-3 px-4 font-semibold text-bne-ink">Series</th>
            <th className="text-left py-3 px-4 font-semibold text-bne-ink">Prediction</th>
            <th className="text-left py-3 px-4 font-semibold text-bne-ink">Risk Score</th>
            <th className="text-left py-3 px-4 font-semibold text-bne-ink">Confidence</th>
            <th className="text-left py-3 px-4 font-semibold text-bne-ink">Insight</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row, index) => (
            <tr key={row.key ?? index} className="border-b border-bne-frost last:border-0 hover:bg-bne-ice/30 transition-colors">
              <td className="py-3 px-4 font-medium text-bne-ink">{row.label}</td>
              <td className="py-3 px-4 font-mono text-bne-ink">{formatNumber(row.prediction)}</td>
              <td className="py-3 px-4 font-mono text-bne-ink">{formatNumber(row.risk)}</td>
              <td className="py-3 px-4 font-mono text-bne-steel">
                {row.confidence
                  ? `${formatNumber(row.confidence.lower)} – ${formatNumber(row.confidence.upper)}`
                  : '—'}
              </td>
              <td className="py-3 px-4 text-sm text-bne-steel">{row.explanation || '—'}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

export default function Results({ params = {} }) {
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

  const [scenario, setScenario] = useState(null)
  const [scenarioLoading, setScenarioLoading] = useState(false)
  const [scenarioError, setScenarioError] = useState(null)
  const [scenarioReloadKey, setScenarioReloadKey] = useState(0)
  const [builderName, setBuilderName] = useState('')
  const [builderHorizon, setBuilderHorizon] = useState(30)
  const [builderAdjustments, setBuilderAdjustments] = useState({})
  const [builderError, setBuilderError] = useState(null)
  const [builderLoading, setBuilderLoading] = useState(false)
  const builderRef = useRef(null)

  const baselineMetrics = modelDetail?.result || {}
  const perSourceMetrics = baselineMetrics?.per_source_metrics || {}
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
          const payload = await response.json().catch(() => ({}))
          const message =
            payload?.detail?.user_friendly ||
            payload?.detail ||
            response.statusText ||
            'Failed to load scenario results.'
          throw new Error(message)
        }
        const data = await response.json()
        if (!cancelled) {
          setScenario(data)
        }
      } catch (error) {
        if (!cancelled) {
          setScenario(null)
          setScenarioError(error.message || 'Failed to load scenario results.')
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
    const template = {}
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

  const summaryCards = (() => {
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

    const cards = []
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

  const predictionsRows = (() => {
    if (Array.isArray(scenario?.predictions) && scenario.predictions.length) {
      return scenario.predictions.map((item, index) => ({
        key: item.source ?? item.bank_id ?? index,
        label: item.source || item.bank_name || `Series ${index + 1}`,
        prediction: item.prediction ?? item.overall_risk,
        risk: item.risk_score ?? item.overall_risk,
        confidence:
          item.confidence_lower !== undefined && item.confidence_upper !== undefined
            ? { lower: item.confidence_lower, upper: item.confidence_upper }
            : null,
        explanation: item.explanation
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
      explanation: entry.explanation
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

  const modelInfoRows = [
    { label: 'Model ID', value: modelDetail?.model_id ?? modelId },
    { label: 'Status', value: modelDetail?.status },
    { label: 'Model Type', value: baselineMetrics?.model_type || baselineMetrics?.config?.model_type },
    { label: 'Version', value: baselineMetrics?.model_version },
    { label: 'Created', value: formatDate(modelDetail?.created_at) },
    { label: 'Completed', value: formatDate(modelDetail?.completed_at) },
    { label: 'Data Job', value: modelDetail?.data_job_id ? `Job ${modelDetail.data_job_id}` : null },
    { label: 'Predictions Path', value: modelDetail?.predictions_path }
  ].filter((item) => item.value !== undefined && item.value !== null && item.value !== '')

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
        const payload = await response.json().catch(() => ({}))
        const message =
          payload?.detail?.user_friendly ||
          payload?.detail ||
          response.statusText ||
          'Scenario simulation failed.'
        throw new Error(message)
      }
      const data = await response.json()
      setScenario(data)
      setBuilderName(data.name)
    } catch (error) {
      setBuilderError(error.message || 'Scenario simulation failed.')
    } finally {
      setBuilderLoading(false)
    }
  }

  const resetAdjustments = () => {
    const template = {}
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
          <Button variant="outline" size="sm" onClick={() => navigate('models', { modelId })}>
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
              <p className="text-sm text-bne-steel">
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
                      className="w-full px-3 py-2 border border-bne-frost rounded-lg focus:outline-none focus:ring-2 focus:ring-bne-azure"
                      placeholder="e.g., Volatility +20%"
                    />
                  </div>
                  <div>
                    <label className="block text-xs font-medium text-bne-ink mb-1">Horizon (days)</label>
                    <select
                      value={builderHorizon}
                      onChange={(event) => setBuilderHorizon(Number(event.target.value))}
                      className="w-full px-3 py-2 border border-bne-frost rounded-lg focus:outline-none focus:ring-2 focus:ring-bne-azure"
                    >
                      {[7, 14, 30, 60, 90].map((value) => (
                        <option key={value} value={value}>
                          {value} days
                        </option>
                      ))}
                    </select>
                  </div>
                  <div className="rounded-lg border border-bne-frost bg-bne-ice/60 p-3 text-xs text-bne-steel">
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
                          <span className="text-bne-steel">{formatted}%</span>
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
                  <div className="rounded-lg border border-bne-crimson/30 bg-bne-crimson/10 px-3 py-2 text-xs text-bne-crimson">
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
                      <span className="text-bne-steel">{item.name}</span>
                      <span className="font-medium text-bne-ink">{formatNumber(item.value)}</span>
                    </div>
                    <div className="w-full h-2 bg-bne-frost rounded-full overflow-hidden">
                      <div
                        className="h-full bg-gradient-to-r from-bne-azure to-bne-indigo transition-all duration-300"
                        style={{ width: `${Math.min(Math.abs(item.value) * 100, 100)}%` }}
                      />
                    </div>
                  </div>
                ))}
                {!featureDrivers.length && (
                  <p className="text-sm text-bne-steel">No drivers available.</p>
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
                  <p className="text-bne-steel">{row.label}</p>
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

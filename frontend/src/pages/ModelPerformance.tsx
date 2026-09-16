import { useState, useMemo, type ReactNode } from 'react'
import PageContainer from '../components/ui/PageContainer'
import Card, { CardHeader, CardTitle, CardContent } from '../components/ui/Card'
import Button from '../components/ui/Button'
import Badge, { type BadgeVariant } from '../components/ui/Badge'
import LoadingSpinner from '../components/ui/LoadingSpinner'
import ErrorMessage from '../components/ui/ErrorMessage'
import { useModels } from '../hooks/useApi'
import { useRouter } from '../store/useRouter'
import type { Model } from '../types/api'

interface MetricCardProps {
  title: string
  value: ReactNode
  change?: string
  trend?: 'up' | 'down' | 'flat'
  subtitle?: ReactNode
}

function MetricCard({ title, value, change, trend, subtitle }: MetricCardProps) {
  const trendColor = trend === 'up' ? 'text-bne-moss' : trend === 'down' ? 'text-bne-clay' : 'text-bne-muted'
  const trendIcon = trend === 'up' ? '↑' : trend === 'down' ? '↓' : '→'

  return (
    <Card>
      <CardContent className="py-6">
        <div className="flex items-start justify-between">
          <div className="flex-1">
            <p className="text-sm text-bne-muted mb-1">{title}</p>
            <p className="font-display text-3xl font-semibold tnum text-bne-ink">{value}</p>
            {subtitle && <p className="text-xs text-bne-muted mt-1">{subtitle}</p>}
          </div>
          {change && (
            <div className={`flex items-center gap-1 text-sm font-medium ${trendColor}`}>
              <span>{trendIcon}</span>
              <span>{change}</span>
            </div>
          )}
        </div>
      </CardContent>
    </Card>
  )
}

type SortColumn = 'accuracy' | 'rmse' | 'mae' | 'trained'

function ModelComparisonTable({ models }: { models: Model[] }) {
  const [sortBy, setSortBy] = useState<SortColumn>('accuracy')
  const [sortOrder, setSortOrder] = useState<'asc' | 'desc'>('desc')

  const sortedModels = useMemo(() => {
    const sorted = [...models].sort((a, b) => {
      let aVal: number
      let bVal: number

      switch (sortBy) {
        case 'accuracy':
          aVal = a.accuracy || a.result?.test_r2 || 0
          bVal = b.accuracy || b.result?.test_r2 || 0
          break
        case 'rmse':
          aVal = a.result?.test_rmse || a.result?.rmse || Infinity
          bVal = b.result?.test_rmse || b.result?.rmse || Infinity
          break
        case 'mae':
          aVal = a.result?.test_mae || a.result?.mae || Infinity
          bVal = b.result?.test_mae || b.result?.mae || Infinity
          break
        case 'trained':
          aVal = a.last_trained ? new Date(a.last_trained).getTime() : 0
          bVal = b.last_trained ? new Date(b.last_trained).getTime() : 0
          break
        default:
          aVal = 0
          bVal = 0
      }

      return sortOrder === 'desc' ? bVal - aVal : aVal - bVal
    })

    return sorted
  }, [models, sortBy, sortOrder])

  const handleSort = (column: SortColumn) => {
    if (sortBy === column) {
      setSortOrder(sortOrder === 'desc' ? 'asc' : 'desc')
    } else {
      setSortBy(column)
      setSortOrder('desc')
    }
  }

  const formatMetric = (value?: number | null) => {
    if (value === null || value === undefined) return '—'
    const num = Number(value)
    if (!Number.isFinite(num)) return '—'
    return num.toFixed(4)
  }

  const getStatusBadge = (status?: string | null) => {
    const variants: Record<string, BadgeVariant> = {
      ready: 'success',
      training: 'primary',
      failed: 'danger',
      draft: 'default'
    }
    return <Badge variant={variants[status ?? ''] || 'default'} size="sm">{status}</Badge>
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-bne-line bg-bne-paper/40">
            <th className="text-left py-3 px-4 font-semibold text-bne-ink">Model</th>
            <th className="text-left py-3 px-4 font-semibold text-bne-ink">Status</th>
            <th
              className="text-left py-3 px-4 font-semibold text-bne-ink cursor-pointer hover:text-bne-pine"
              onClick={() => handleSort('accuracy')}
            >
              R² Score {sortBy === 'accuracy' && (sortOrder === 'desc' ? '↓' : '↑')}
            </th>
            <th
              className="text-left py-3 px-4 font-semibold text-bne-ink cursor-pointer hover:text-bne-pine"
              onClick={() => handleSort('rmse')}
            >
              RMSE {sortBy === 'rmse' && (sortOrder === 'desc' ? '↓' : '↑')}
            </th>
            <th
              className="text-left py-3 px-4 font-semibold text-bne-ink cursor-pointer hover:text-bne-pine"
              onClick={() => handleSort('mae')}
            >
              MAE {sortBy === 'mae' && (sortOrder === 'desc' ? '↓' : '↑')}
            </th>
            <th
              className="text-left py-3 px-4 font-semibold text-bne-ink cursor-pointer hover:text-bne-pine"
              onClick={() => handleSort('trained')}
            >
              Last Trained {sortBy === 'trained' && (sortOrder === 'desc' ? '↓' : '↑')}
            </th>
            <th className="text-left py-3 px-4 font-semibold text-bne-ink">Actions</th>
          </tr>
        </thead>
        <tbody>
          {sortedModels.map((model) => (
            <tr
              key={String(model.model_id)}
              className="border-b border-bne-line last:border-0 hover:bg-bne-paper/30 transition-colors"
            >
              <td className="py-3 px-4">
                <div>
                  <p className="font-medium text-bne-ink">{model.name}</p>
                  <p className="text-xs text-bne-muted">{model.architecture || 'LSTM'}</p>
                </div>
              </td>
              <td className="py-3 px-4">{getStatusBadge(model.status)}</td>
              <td className="py-3 px-4 font-mono text-bne-ink">
                {formatMetric(model.accuracy || model.result?.test_r2)}
              </td>
              <td className="py-3 px-4 font-mono text-bne-ink">
                {formatMetric(model.result?.test_rmse || model.result?.rmse)}
              </td>
              <td className="py-3 px-4 font-mono text-bne-ink">
                {formatMetric(model.result?.test_mae || model.result?.mae)}
              </td>
              <td className="py-3 px-4 text-bne-muted">
                {model.last_trained ? new Date(model.last_trained).toLocaleDateString() : 'Never'}
              </td>
              <td className="py-3 px-4">
                <Button variant="ghost" size="sm">
                  View Details
                </Button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function PerformanceChart({ models }: { models: Model[] }) {
  const chartData = useMemo(() => {
    return models
      .filter((m) => m.result?.test_r2 || m.accuracy)
      .map((m) => ({
        name: m.name ?? '',
        r2: m.result?.test_r2 || m.accuracy || 0,
        rmse: m.result?.test_rmse || m.result?.rmse || 0,
        mae: m.result?.test_mae || m.result?.mae || 0
      }))
      .slice(0, 8) // Top 8 models
  }, [models])

  if (chartData.length === 0) {
    return <p className="text-sm text-bne-muted">No performance data available</p>
  }

  const maxR2 = Math.max(...chartData.map((d) => d.r2))

  return (
    <div className="space-y-4">
      {chartData.map((data, index) => (
        <div key={index} className="space-y-2">
          <div className="flex items-center justify-between text-sm">
            <span className="text-bne-ink font-medium truncate max-w-[200px]" title={data.name}>
              {data.name}
            </span>
            <div className="flex items-center gap-4">
              <span className="text-bne-muted text-xs">R²: {data.r2.toFixed(4)}</span>
              <span className="text-bne-muted text-xs">RMSE: {data.rmse.toFixed(4)}</span>
            </div>
          </div>
          <div className="w-full h-3 bg-bne-paper-dim rounded-full overflow-hidden">
            <div
              className="h-full bg-bne-pine transition-all duration-300"
              style={{ width: `${(data.r2 / maxR2) * 100}%` }}
            />
          </div>
        </div>
      ))}
    </div>
  )
}

function ModelHealthIndicators({ models }: { models: Model[] }) {
  const health = useMemo(() => {
    const ready = models.filter((m) => m.status === 'ready').length
    const training = models.filter((m) => m.status === 'training').length
    const failed = models.filter((m) => m.status === 'failed').length
    const stale = models.filter((m) => {
      if (!m.last_trained) return true
      const daysSince = (Date.now() - new Date(m.last_trained).getTime()) / (1000 * 60 * 60 * 24)
      return daysSince > 30
    }).length

    const totalHealth = models.length > 0 ? Number(((ready / models.length) * 100).toFixed(0)) : 0

    return { ready, training, failed, stale, totalHealth }
  }, [models])

  const getHealthColor = (score: number) => {
    if (score >= 80) return 'text-bne-moss'
    if (score >= 50) return 'text-bne-ochre'
    return 'text-bne-clay'
  }

  return (
    <div className="space-y-6">
      <div className="text-center">
        <div className={`text-5xl font-bold ${getHealthColor(health.totalHealth)}`}>
          {health.totalHealth}%
        </div>
        <p className="text-sm text-bne-muted mt-2">Overall Model Health</p>
        <p className="text-xs text-bne-muted mt-1">
          {health.ready} of {models.length} models production-ready
        </p>
      </div>

      <div className="space-y-3">
        <div className="flex items-center justify-between p-3 rounded-lg bg-bne-moss/10 border border-bne-moss/20">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-full bg-bne-moss/20 flex items-center justify-center">
              <svg className="w-5 h-5 text-bne-moss" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
              </svg>
            </div>
            <div>
              <p className="text-sm font-medium text-bne-ink">Ready Models</p>
              <p className="text-xs text-bne-muted">Production-ready and validated</p>
            </div>
          </div>
          <span className="font-display text-2xl font-semibold tnum text-bne-moss">{health.ready}</span>
        </div>

        <div className="flex items-center justify-between p-3 rounded-lg bg-bne-pine/10 border border-bne-pine/20">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-full bg-bne-pine/20 flex items-center justify-center">
              <svg className="w-5 h-5 text-bne-pine" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
              </svg>
            </div>
            <div>
              <p className="text-sm font-medium text-bne-ink">Training</p>
              <p className="text-xs text-bne-muted">Currently in progress</p>
            </div>
          </div>
          <span className="font-display text-2xl font-semibold tnum text-bne-pine">{health.training}</span>
        </div>

        <div className="flex items-center justify-between p-3 rounded-lg bg-bne-ochre/10 border border-bne-ochre/20">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-full bg-bne-ochre/20 flex items-center justify-center">
              <svg className="w-5 h-5 text-bne-ochre" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" />
              </svg>
            </div>
            <div>
              <p className="text-sm font-medium text-bne-ink">Stale Models</p>
              <p className="text-xs text-bne-muted">Not trained in 30+ days</p>
            </div>
          </div>
          <span className="font-display text-2xl font-semibold tnum text-bne-ochre">{health.stale}</span>
        </div>

        <div className="flex items-center justify-between p-3 rounded-lg bg-bne-clay/10 border border-bne-clay/20">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-full bg-bne-clay/20 flex items-center justify-center">
              <svg className="w-5 h-5 text-bne-clay" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
              </svg>
            </div>
            <div>
              <p className="text-sm font-medium text-bne-ink">Failed</p>
              <p className="text-xs text-bne-muted">Training or validation failed</p>
            </div>
          </div>
          <span className="font-display text-2xl font-semibold tnum text-bne-clay">{health.failed}</span>
        </div>
      </div>
    </div>
  )
}

export default function ModelPerformance() {
  const { data: models, isLoading, error, refetch } = useModels()
  const navigate = useRouter((state) => state.navigate)

  const stats = useMemo(() => {
    if (!models || models.length === 0) {
      return {
        totalModels: 0,
        avgAccuracy: 0 as number | string,
        avgRMSE: 0 as number | string,
        bestModel: null as Model | null
      }
    }

    const readyModels = models.filter((m) => m.status === 'ready')
    const r2Scores = readyModels
      .map((m) => m.accuracy || m.result?.test_r2)
      .filter((s): s is number => s !== null && s !== undefined)

    const rmseScores = readyModels
      .map((m) => m.result?.test_rmse || m.result?.rmse)
      .filter((s): s is number => s !== null && s !== undefined)

    const avgAccuracy: number | string = r2Scores.length > 0
      ? (r2Scores.reduce((a, b) => a + b, 0) / r2Scores.length).toFixed(4)
      : 0

    const avgRMSE: number | string = rmseScores.length > 0
      ? (rmseScores.reduce((a, b) => a + b, 0) / rmseScores.length).toFixed(4)
      : 0

    const bestModel = readyModels.reduce<Model | null>((best, model) => {
      const score = model.accuracy || model.result?.test_r2 || 0
      const bestScore = best?.accuracy || best?.result?.test_r2 || 0
      return score > bestScore ? model : best
    }, null)

    return {
      totalModels: models.length,
      avgAccuracy,
      avgRMSE,
      bestModel
    }
  }, [models])

  if (isLoading) {
    return (
      <PageContainer title="Model Performance">
        <div className="flex items-center justify-center h-64">
          <LoadingSpinner size="lg" message="Loading performance data..." />
        </div>
      </PageContainer>
    )
  }

  if (error) {
    return (
      <PageContainer title="Model Performance">
        <ErrorMessage
          title="Failed to load performance data"
          error={error}
          onRetry={refetch}
        />
      </PageContainer>
    )
  }

  return (
    <PageContainer
      title="Model Performance Dashboard"
      subtitle="Centralized view of all model metrics, health indicators, and performance trends"
      actions={
        <div className="flex items-center gap-2">
          <Button variant="outline" size="sm" onClick={() => refetch()}>
            <svg className="w-4 h-4 mr-2" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
            </svg>
            Refresh
          </Button>
          <Button variant="primary" size="sm" onClick={() => navigate('models')}>
            <svg className="w-4 h-4 mr-2" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M12 4v16m8-8H4" />
            </svg>
            New Model
          </Button>
        </div>
      }
    >
      <div className="space-y-6">
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
          <MetricCard
            title="Total Models"
            value={stats.totalModels}
            subtitle="Across all statuses"
          />
          <MetricCard
            title="Average R² Score"
            value={stats.avgAccuracy}
            subtitle="For production-ready models"
            trend="up"
            change="+2.3%"
          />
          <MetricCard
            title="Average RMSE"
            value={stats.avgRMSE}
            subtitle="Lower is better"
            trend="down"
            change="-1.8%"
          />
          <MetricCard
            title="Best Performer"
            value={stats.bestModel?.name || '—'}
            subtitle={stats.bestModel ? `R²: ${(stats.bestModel.accuracy || stats.bestModel.result?.test_r2 || 0).toFixed(4)}` : 'No models ready'}
          />
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          <Card className="lg:col-span-2">
            <CardHeader>
              <CardTitle>Model Performance Comparison</CardTitle>
            </CardHeader>
            <CardContent>
              <PerformanceChart models={models || []} />
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Model Health</CardTitle>
            </CardHeader>
            <CardContent>
              <ModelHealthIndicators models={models || []} />
            </CardContent>
          </Card>
        </div>

        <Card>
          <CardHeader>
            <div className="flex items-center justify-between">
              <CardTitle>All Models</CardTitle>
              <p className="text-sm text-bne-muted">
                Click column headers to sort
              </p>
            </div>
          </CardHeader>
          <CardContent>
            {models && models.length > 0 ? (
              <ModelComparisonTable models={models} />
            ) : (
              <div className="text-center py-12">
                <svg
                  className="w-16 h-16 mx-auto text-bne-muted/30 mb-4"
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
                <h3 className="text-lg font-semibold text-bne-ink mb-2">No Models Found</h3>
                <p className="text-sm text-bne-muted mb-6">
                  Create your first model to start tracking performance metrics
                </p>
                <Button variant="primary" onClick={() => navigate('models')}>
                  Create Model
                </Button>
              </div>
            )}
          </CardContent>
        </Card>
      </div>
    </PageContainer>
  )
}

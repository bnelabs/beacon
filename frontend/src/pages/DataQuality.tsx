import { useMemo, type ReactNode } from 'react'
import Card, { CardHeader, CardTitle, CardContent } from '../components/ui/Card'
import Badge from '../components/ui/Badge'
import LoadingSpinner from '../components/ui/LoadingSpinner'
import { useDataQualityStats, useSourceQualityDetails, useQualityTrends } from '../hooks/useDataQuality'
import { useDataSourceHealth } from '../hooks/useApi'
import type {
  DataQualityAnomalies,
  DataQualityFreshness,
  QualityTrendPoint,
  SourceQualityRow
} from '../types/api'

/**
 * Quality and completeness arrive on the gate's own scale: 0-100 percentages
 * (`QualityPolicy.min_quality_score = 70`, `min_completeness = 80`, and
 * `completeness = 100 * (1 - missing_ratio)`). They are rendered verbatim as
 * percentages here — never multiplied by 100 a second time.
 *
 * The bands are those floors, not decoration: 70 is the score under which the
 * data-quality gate refuses a dataset outright, 90 is the band this page's
 * completeness card already used. They were 0.7/0.5 for as long as this page
 * existed, which read a real 85.6 as 8560% and coloured it "excellent".
 */
const QUALITY_EXCELLENT = 90
const QUALITY_GOOD = 70

interface MetricCardProps {
  title: string
  value: ReactNode
  subtitle?: ReactNode
  trend?: number
  status?: 'excellent' | 'good' | 'warning' | string | null
}

function MetricCard({ title, value, subtitle, trend, status }: MetricCardProps) {
  const getStatusColor = () => {
    if (!status) return 'text-bne-ink'
    if (status === 'excellent') return 'text-bne-moss'
    if (status === 'good') return 'text-bne-pine'
    if (status === 'warning') return 'text-bne-ochre'
    return 'text-bne-clay'
  }

  return (
    <Card>
      <CardContent className="p-6">
        <div className="flex items-center justify-between mb-2">
          <h3 className="text-sm font-medium text-bne-muted">{title}</h3>
          {trend != null && (
            <span className={`text-xs ${trend > 0 ? 'text-bne-moss' : 'text-bne-clay'}`}>
              {trend > 0 ? '↑' : '↓'} {Math.abs(trend)}%
            </span>
          )}
        </div>
        <div className={`font-display text-3xl font-semibold tnum ${getStatusColor()}`}>{value}</div>
        {subtitle && <p className="text-sm text-bne-muted mt-1">{subtitle}</p>}
      </CardContent>
    </Card>
  )
}

function FreshnessIndicator({ freshness }: { freshness: DataQualityFreshness }) {
  const getStatusInfo = () => {
    const { fresh, stale, outdated, never_synced } = freshness
    const total = fresh + stale + outdated + never_synced

    return [
      { label: 'Fresh', count: fresh, color: 'bg-bne-moss', percentage: (fresh / total) * 100 },
      { label: 'Stale', count: stale, color: 'bg-bne-ochre', percentage: (stale / total) * 100 },
      { label: 'Outdated', count: outdated, color: 'bg-bne-clay', percentage: (outdated / total) * 100 },
      { label: 'Never Synced', count: never_synced, color: 'bg-bne-muted', percentage: (never_synced / total) * 100 }
    ]
  }

  const statusInfo = getStatusInfo()

  return (
    <Card>
      <CardHeader>
        <CardTitle>Data Freshness</CardTitle>
      </CardHeader>
      <CardContent>
        <div className="space-y-4">
          {/* Progress bar */}
          <div className="w-full h-8 bg-bne-paper-dim rounded-lg overflow-hidden flex">
            {statusInfo.map((status) => (
              status.count > 0 && (
                <div
                  key={status.label}
                  className={`${status.color} flex items-center justify-center text-bne-chalk text-xs font-medium`}
                  style={{ width: `${status.percentage}%` }}
                  title={`${status.label}: ${status.count}`}
                >
                  {status.percentage > 15 && status.count}
                </div>
              )
            ))}
          </div>

          {/* Legend */}
          <div className="grid grid-cols-2 gap-3">
            {statusInfo.map((status) => (
              <div key={status.label} className="flex items-center gap-2">
                <div className={`w-3 h-3 rounded ${status.color}`} />
                <span className="text-sm text-bne-muted">
                  {status.label}: <span className="font-medium text-bne-ink">{status.count}</span>
                </span>
              </div>
            ))}
          </div>

          <div className="mt-4 pt-4 border-t border-bne-line">
            <div className="text-center">
              <div className="font-display text-2xl font-semibold tnum text-bne-ink">{freshness.freshness_percentage}%</div>
              <div className="text-sm text-bne-muted">Data Sources Up to Date</div>
            </div>
          </div>
        </div>
      </CardContent>
    </Card>
  )
}

function QualityTrendChart({ trends }: { trends: QualityTrendPoint[] }) {
  const chartData = useMemo(() => {
    if (!Array.isArray(trends) || trends.length === 0) return []

    // Take last 14 days for visualization
    return trends.slice(-14)
  }, [trends])

  const maxValue = useMemo(() => {
    if (chartData.length === 0) return 1
    const values = chartData.map((d) => d.avg_quality_score || 0)
    return Math.max(...values, 1)
  }, [chartData])

  if (chartData.length === 0) {
    return (
      <div className="text-center py-12 text-bne-muted">
        <p>No quality trend data available</p>
      </div>
    )
  }

  return (
    <div className="space-y-2">
      {/* Chart */}
      <div className="h-48 flex items-end gap-1">
        {chartData.map((day) => {
          const height = ((day.avg_quality_score || 0) / maxValue) * 100
          const color =
            day.avg_quality_score >= QUALITY_GOOD ? 'bg-bne-moss' : day.avg_quality_score >= 50 ? 'bg-bne-ochre' : 'bg-bne-clay'

          return (
            <div
              key={day.date}
              className="flex-1 flex flex-col items-center gap-1 group cursor-pointer"
              title={`${day.date}: ${(day.avg_quality_score ?? 0).toFixed(1)}% quality`}
            >
              <div className="w-full relative flex items-end" style={{ height: '160px' }}>
                <div
                  className={`w-full ${color} rounded-t transition-all group-hover:opacity-80`}
                  style={{ height: `${height}%` }}
                />
              </div>
              <div className="text-xs text-bne-muted whitespace-nowrap rotate-45 origin-left">
                {new Date(day.date).toLocaleDateString('en-US', { month: 'short', day: 'numeric' })}
              </div>
            </div>
          )
        })}
      </div>

      {/* Legend */}
      <div className="flex items-center justify-center gap-6 pt-4 text-xs text-bne-muted">
        <div className="flex items-center gap-2">
          <div className="w-3 h-3 rounded bg-bne-moss" />
          <span>High Quality ≥70%</span>
        </div>
        <div className="flex items-center gap-2">
          <div className="w-3 h-3 rounded bg-bne-ochre" />
          <span>Medium 50-70%</span>
        </div>
        <div className="flex items-center gap-2">
          <div className="w-3 h-3 rounded bg-bne-clay" />
          <span>Low &lt;50%</span>
        </div>
      </div>
    </div>
  )
}

function SourceQualityTable({ sources }: { sources: SourceQualityRow[] }) {
  const sortedSources = useMemo(() => {
    return [...(Array.isArray(sources) ? sources : [])].sort((a, b) => {
      // Sort by freshness first, then quality
      const freshnessOrder: Record<string, number> = { fresh: 0, stale: 1, outdated: 2, never_synced: 3 }
      if (freshnessOrder[a.freshness_status] !== freshnessOrder[b.freshness_status]) {
        return freshnessOrder[a.freshness_status] - freshnessOrder[b.freshness_status]
      }
      return (b.avg_quality_score || 0) - (a.avg_quality_score || 0)
    })
  }, [sources])

  const getFreshnessColor = (status: string) => {
    switch (status) {
      case 'fresh': return 'text-bne-moss bg-bne-moss/10'
      case 'stale': return 'text-bne-ochre bg-bne-ochre/10'
      case 'outdated': return 'text-bne-clay bg-bne-clay/10'
      default: return 'text-bne-muted bg-bne-muted/10'
    }
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full">
        <thead>
          <tr className="border-b border-bne-line">
            <th className="text-left py-3 px-4 text-sm font-semibold text-bne-ink">Source</th>
            <th className="text-left py-3 px-4 text-sm font-semibold text-bne-ink">Type</th>
            <th className="text-left py-3 px-4 text-sm font-semibold text-bne-ink">Status</th>
            <th className="text-left py-3 px-4 text-sm font-semibold text-bne-ink">Freshness</th>
            <th className="text-right py-3 px-4 text-sm font-semibold text-bne-ink">Quality Score</th>
            <th className="text-right py-3 px-4 text-sm font-semibold text-bne-ink">Last Updated</th>
          </tr>
        </thead>
        <tbody>
          {sortedSources.map((source) => (
            <tr key={String(source.id)} className="border-b border-bne-line hover:bg-bne-paper/30 transition-colors">
              <td className="py-3 px-4">
                <div className="font-medium text-bne-ink">{source.name}</div>
              </td>
              <td className="py-3 px-4">
                <span className="text-sm text-bne-muted">{source.plugin_type}</span>
              </td>
              <td className="py-3 px-4">
                <Badge
                  variant={source.status === 'active' && source.enabled ? 'success' : source.status === 'error' ? 'danger' : 'default'}
                  size="sm"
                >
                  {source.enabled ? source.status : 'disabled'}
                </Badge>
              </td>
              <td className="py-3 px-4">
                <span className={`px-2 py-1 rounded-full text-xs font-medium ${getFreshnessColor(source.freshness_status)}`}>
                  {source.freshness_status.replace('_', ' ')}
                  {source.days_since_update !== null && ` (${source.days_since_update}d)`}
                </span>
              </td>
              <td className="py-3 px-4 text-right">
                {source.avg_quality_score !== null ? (
                  <span className={`font-mono font-medium ${
                    source.avg_quality_score >= QUALITY_GOOD ? 'text-bne-moss' :
                    source.avg_quality_score >= 50 ? 'text-bne-ochre' : 'text-bne-clay'
                  }`}>
                    {source.avg_quality_score.toFixed(1)}%
                  </span>
                ) : (
                  <span className="text-bne-muted text-sm">N/A</span>
                )}
              </td>
              <td className="py-3 px-4 text-right text-sm text-bne-muted">
                {source.last_fetch ? new Date(source.last_fetch).toLocaleDateString() : 'Never'}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

interface QualityAlert {
  severity: 'warning' | 'error'
  title: string
  message: string
}

function AnomalyAlerts({ anomalies }: { anomalies: DataQualityAnomalies }) {
  const alerts = useMemo<QualityAlert[]>(() => {
    const result: QualityAlert[] = []

    if (anomalies.low_quality_jobs > 0) {
      result.push({
        severity: 'warning',
        title: `${anomalies.low_quality_jobs} Low Quality Jobs`,
        message: 'Recent data ingestion jobs have quality scores below threshold'
      })
    }

    if (anomalies.error_sources > 0) {
      result.push({
        severity: 'error',
        title: `${anomalies.error_sources} Sources in Error State`,
        message: 'Some data sources are experiencing errors and need attention'
      })
    }

    if (anomalies.recent_failures > 0) {
      result.push({
        severity: 'error',
        title: `${anomalies.recent_failures} Recent Job Failures`,
        message: 'Data ingestion jobs have failed in the past 7 days'
      })
    }

    if (anomalies.stale_sources > 0) {
      result.push({
        severity: 'warning',
        title: `${anomalies.stale_sources} Stale Data Sources`,
        message: 'Some sources have not been updated recently'
      })
    }

    return result
  }, [anomalies])

  if (alerts.length === 0) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>Anomaly Alerts</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="flex items-center gap-3 py-8 text-bne-moss">
            <svg className="w-12 h-12" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" />
            </svg>
            <div>
              <p className="font-semibold text-bne-ink">All Clear</p>
              <p className="text-sm text-bne-muted">No data quality issues detected</p>
            </div>
          </div>
        </CardContent>
      </Card>
    )
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Anomaly Alerts</CardTitle>
      </CardHeader>
      <CardContent>
        <div className="space-y-3">
          {alerts.map((alert, index) => (
            <div
              key={index}
              className={`flex items-start gap-3 p-3 rounded-lg ${
                alert.severity === 'error' ? 'bg-bne-clay/10 border border-bne-clay/20' : 'bg-bne-ochre/10 border border-bne-ochre/20'
              }`}
            >
              <svg
                className={`w-5 h-5 flex-shrink-0 mt-0.5 ${alert.severity === 'error' ? 'text-bne-clay' : 'text-bne-ochre'}`}
                fill="none"
                viewBox="0 0 24 24"
                stroke="currentColor"
                strokeWidth={2}
              >
                <path strokeLinecap="round" strokeLinejoin="round" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
              </svg>
              <div>
                <p className={`font-semibold text-sm ${alert.severity === 'error' ? 'text-bne-clay' : 'text-bne-ochre'}`}>
                  {alert.title}
                </p>
                <p className="text-sm text-bne-muted mt-1">{alert.message}</p>
              </div>
            </div>
          ))}
        </div>
      </CardContent>
    </Card>
  )
}

export default function DataQuality() {
  const { data: stats, isLoading: statsLoading, error: statsError } = useDataQualityStats()
  const { data: sources, isLoading: sourcesLoading } = useSourceQualityDetails()
  const { data: trendsData, isLoading: trendsLoading } = useQualityTrends(30)
  const { data: healthPayload } = useDataSourceHealth()

  // Scheduled feeds only: a manual source has no cadence to keep, and showing
  // "overdue" for a feed nobody promised to refresh would be a false alarm.
  // (Above the early returns: hooks must run in the same order every render.)
  const scheduledHealth = useMemo(
    () => (healthPayload?.sources || []).filter((row) => row.scheduled),
    [healthPayload]
  )

  if (statsLoading || sourcesLoading || trendsLoading) {
    return (
      <div className="flex items-center justify-center h-[60vh]">
        <LoadingSpinner message="Loading data quality metrics..." />
      </div>
    )
  }

  if (statsError) {
    return (
      <div className="p-6">
        <Card>
          <CardContent className="p-6">
            <div className="text-center text-bne-clay">
              <p className="font-semibold">Error loading data quality metrics</p>
              <p className="text-sm text-bne-muted mt-2">{statsError.message}</p>
            </div>
          </CardContent>
        </Card>
      </div>
    )
  }

  if (!stats) {
    return null
  }

  const { overview, freshness, quality, anomalies } = stats

  return (
    <div className="p-6 space-y-6">
      {/* Header */}
      <div>
        <h1 className="font-display text-2xl font-semibold tnum text-bne-ink mb-2">Data Quality Monitoring</h1>
        <p className="text-bne-muted">Monitor data completeness, freshness, and quality across all sources</p>
      </div>

      {/* Summary Metrics */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
        <MetricCard
          title="Overall Health"
          value={`${overview.overall_health}%`}
          subtitle={`${overview.active_sources}/${overview.total_sources} sources active`}
          status={overview.overall_health >= 80 ? 'excellent' : overview.overall_health >= 50 ? 'good' : 'warning'}
        />
        <MetricCard
          title="Avg Quality Score"
          value={`${quality.avg_quality_score.toFixed(1)}%`}
          subtitle={`Based on ${quality.jobs_analyzed} jobs`}
          status={quality.avg_quality_score >= QUALITY_EXCELLENT ? 'excellent' : quality.avg_quality_score >= QUALITY_GOOD ? 'good' : 'warning'}
        />
        <MetricCard
          title="Data Completeness"
          value={quality.avg_completeness == null ? '—' : `${quality.avg_completeness.toFixed(1)}%`}
          subtitle="Average across all sources"
          status={
            quality.avg_completeness == null
              ? 'warning'
              : quality.avg_completeness >= QUALITY_EXCELLENT
                ? 'excellent'
                : quality.avg_completeness >= QUALITY_GOOD
                  ? 'good'
                  : 'warning'
          }
        />
        <MetricCard
          title="Active Issues"
          value={anomalies.low_quality_jobs + anomalies.error_sources + anomalies.recent_failures}
          subtitle="Requires attention"
          status={
            anomalies.low_quality_jobs + anomalies.error_sources + anomalies.recent_failures === 0 ? 'excellent' : 'warning'
          }
        />
      </div>

      {/* Freshness and Alerts */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <FreshnessIndicator freshness={freshness} />
        <AnomalyAlerts anomalies={anomalies} />
      </div>

      {/* Refresh cadence: what the scheduler promised, versus what happened */}
      {scheduledHealth.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle>Refresh Cadence</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="space-y-2">
              {scheduledHealth.map((row) => (
                <div key={String(row.id)} className="flex flex-wrap items-center justify-between gap-3 text-sm">
                  <span className="font-medium text-bne-ink">{row.name}</span>
                  <span className="text-bne-muted">
                    every{' '}
                    {(row.sync_interval_minutes ?? 0) >= 1440
                      ? `${Math.round((row.sync_interval_minutes ?? 0) / 1440)} d`
                      : (row.sync_interval_minutes ?? 0) >= 60
                        ? `${Math.round((row.sync_interval_minutes ?? 0) / 60)} h`
                        : `${row.sync_interval_minutes} min`}
                    {(row.backoff_factor ?? 1) > 1 ? ` · backing off ×${row.backoff_factor}` : ''}
                  </span>
                  <span className="text-bne-muted">
                    {row.last_successful_fetch
                      ? `last ok ${new Date(row.last_successful_fetch).toLocaleString()}`
                      : 'never succeeded'}
                  </span>
                  {row.collection_running ? (
                    <Badge variant="primary" size="sm">running</Badge>
                  ) : row.overdue ? (
                    <Badge variant="warning" size="sm">overdue</Badge>
                  ) : (
                    <Badge variant="success" size="sm">on cadence</Badge>
                  )}
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      )}

      {/* Quality Trends */}
      <Card>
        <CardHeader>
          <CardTitle>Quality Trends (Last 30 Days)</CardTitle>
        </CardHeader>
        <CardContent>
          <QualityTrendChart trends={trendsData?.trends || []} />
        </CardContent>
      </Card>

      {/* Source Details */}
      <Card>
        <CardHeader>
          <CardTitle>Data Source Details</CardTitle>
        </CardHeader>
        <CardContent>
          {sources && sources.length > 0 ? (
            <SourceQualityTable sources={sources} />
          ) : (
            <div className="text-center py-12 text-bne-muted">
              <p>No data sources configured</p>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  )
}

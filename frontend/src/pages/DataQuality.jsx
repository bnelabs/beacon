import { useMemo } from 'react'
import Card, { CardHeader, CardTitle, CardContent } from '../components/ui/Card'
import Badge from '../components/ui/Badge'
import LoadingSpinner from '../components/ui/LoadingSpinner'
import { useDataQualityStats, useSourceQualityDetails, useQualityTrends } from '../hooks/useDataQuality'

function MetricCard({ title, value, subtitle, trend, status }) {
  const getStatusColor = () => {
    if (!status) return 'text-bne-ink'
    if (status === 'excellent') return 'text-bne-emerald'
    if (status === 'good') return 'text-bne-azure'
    if (status === 'warning') return 'text-bne-amber'
    return 'text-bne-crimson'
  }

  return (
    <Card>
      <CardContent className="p-6">
        <div className="flex items-center justify-between mb-2">
          <h3 className="text-sm font-medium text-bne-steel">{title}</h3>
          {trend && (
            <span className={`text-xs ${trend > 0 ? 'text-bne-emerald' : 'text-bne-crimson'}`}>
              {trend > 0 ? '↑' : '↓'} {Math.abs(trend)}%
            </span>
          )}
        </div>
        <div className={`text-3xl font-bold ${getStatusColor()}`}>{value}</div>
        {subtitle && <p className="text-sm text-bne-steel mt-1">{subtitle}</p>}
      </CardContent>
    </Card>
  )
}

function FreshnessIndicator({ freshness }) {
  const getStatusInfo = () => {
    const { fresh, stale, outdated, never_synced } = freshness
    const total = fresh + stale + outdated + never_synced

    return [
      { label: 'Fresh', count: fresh, color: 'bg-bne-emerald', percentage: (fresh / total) * 100 },
      { label: 'Stale', count: stale, color: 'bg-bne-amber', percentage: (stale / total) * 100 },
      { label: 'Outdated', count: outdated, color: 'bg-bne-crimson', percentage: (outdated / total) * 100 },
      { label: 'Never Synced', count: never_synced, color: 'bg-bne-steel', percentage: (never_synced / total) * 100 }
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
          <div className="w-full h-8 bg-bne-frost rounded-lg overflow-hidden flex">
            {statusInfo.map((status) => (
              status.count > 0 && (
                <div
                  key={status.label}
                  className={`${status.color} flex items-center justify-center text-white text-xs font-medium`}
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
                <span className="text-sm text-bne-steel">
                  {status.label}: <span className="font-medium text-bne-ink">{status.count}</span>
                </span>
              </div>
            ))}
          </div>

          <div className="mt-4 pt-4 border-t border-bne-frost">
            <div className="text-center">
              <div className="text-2xl font-bold text-bne-ink">{freshness.freshness_percentage}%</div>
              <div className="text-sm text-bne-steel">Data Sources Up to Date</div>
            </div>
          </div>
        </div>
      </CardContent>
    </Card>
  )
}

function QualityTrendChart({ trends }) {
  const chartData = useMemo(() => {
    if (!trends || trends.length === 0) return []

    // Take last 14 days for visualization
    return trends.slice(-14)
  }, [trends])

  const maxValue = useMemo(() => {
    if (chartData.length === 0) return 1
    const values = chartData.map(d => d.avg_quality_score || 0)
    return Math.max(...values, 1)
  }, [chartData])

  if (chartData.length === 0) {
    return (
      <div className="text-center py-12 text-bne-steel">
        <p>No quality trend data available</p>
      </div>
    )
  }

  return (
    <div className="space-y-2">
      {/* Chart */}
      <div className="h-48 flex items-end gap-1">
        {chartData.map((day, index) => {
          const height = ((day.avg_quality_score || 0) / maxValue) * 100
          const color = day.avg_quality_score >= 0.7 ? 'bg-bne-emerald' : day.avg_quality_score >= 0.5 ? 'bg-bne-amber' : 'bg-bne-crimson'

          return (
            <div
              key={day.date}
              className="flex-1 flex flex-col items-center gap-1 group cursor-pointer"
              title={`${day.date}: ${(day.avg_quality_score * 100).toFixed(1)}% quality`}
            >
              <div className="w-full relative flex items-end" style={{ height: '160px' }}>
                <div
                  className={`w-full ${color} rounded-t transition-all group-hover:opacity-80`}
                  style={{ height: `${height}%` }}
                />
              </div>
              <div className="text-xs text-bne-steel whitespace-nowrap rotate-45 origin-left">
                {new Date(day.date).toLocaleDateString('en-US', { month: 'short', day: 'numeric' })}
              </div>
            </div>
          )
        })}
      </div>

      {/* Legend */}
      <div className="flex items-center justify-center gap-6 pt-4 text-xs text-bne-steel">
        <div className="flex items-center gap-2">
          <div className="w-3 h-3 rounded bg-bne-emerald" />
          <span>High Quality ≥70%</span>
        </div>
        <div className="flex items-center gap-2">
          <div className="w-3 h-3 rounded bg-bne-amber" />
          <span>Medium 50-70%</span>
        </div>
        <div className="flex items-center gap-2">
          <div className="w-3 h-3 rounded bg-bne-crimson" />
          <span>Low &lt;50%</span>
        </div>
      </div>
    </div>
  )
}

function SourceQualityTable({ sources }) {
  const sortedSources = useMemo(() => {
    return [...sources].sort((a, b) => {
      // Sort by freshness first, then quality
      const freshnessOrder = { fresh: 0, stale: 1, outdated: 2, never_synced: 3 }
      if (freshnessOrder[a.freshness_status] !== freshnessOrder[b.freshness_status]) {
        return freshnessOrder[a.freshness_status] - freshnessOrder[b.freshness_status]
      }
      return (b.avg_quality_score || 0) - (a.avg_quality_score || 0)
    })
  }, [sources])

  const getFreshnessColor = (status) => {
    switch (status) {
      case 'fresh': return 'text-bne-emerald bg-bne-emerald/10'
      case 'stale': return 'text-bne-amber bg-bne-amber/10'
      case 'outdated': return 'text-bne-crimson bg-bne-crimson/10'
      default: return 'text-bne-steel bg-bne-steel/10'
    }
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full">
        <thead>
          <tr className="border-b border-bne-frost">
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
            <tr key={source.id} className="border-b border-bne-frost hover:bg-bne-ice/30 transition-colors">
              <td className="py-3 px-4">
                <div className="font-medium text-bne-ink">{source.name}</div>
              </td>
              <td className="py-3 px-4">
                <span className="text-sm text-bne-steel">{source.plugin_type}</span>
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
                    source.avg_quality_score >= 0.7 ? 'text-bne-emerald' :
                    source.avg_quality_score >= 0.5 ? 'text-bne-amber' : 'text-bne-crimson'
                  }`}>
                    {(source.avg_quality_score * 100).toFixed(1)}%
                  </span>
                ) : (
                  <span className="text-bne-steel text-sm">N/A</span>
                )}
              </td>
              <td className="py-3 px-4 text-right text-sm text-bne-steel">
                {source.last_fetch ? new Date(source.last_fetch).toLocaleDateString() : 'Never'}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function AnomalyAlerts({ anomalies }) {
  const alerts = useMemo(() => {
    const result = []

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
          <div className="flex items-center gap-3 py-8 text-bne-emerald">
            <svg className="w-12 h-12" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" />
            </svg>
            <div>
              <p className="font-semibold text-bne-ink">All Clear</p>
              <p className="text-sm text-bne-steel">No data quality issues detected</p>
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
                alert.severity === 'error' ? 'bg-bne-crimson/10 border border-bne-crimson/20' : 'bg-bne-amber/10 border border-bne-amber/20'
              }`}
            >
              <svg
                className={`w-5 h-5 flex-shrink-0 mt-0.5 ${alert.severity === 'error' ? 'text-bne-crimson' : 'text-bne-amber'}`}
                fill="none"
                viewBox="0 0 24 24"
                stroke="currentColor"
              >
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
              </svg>
              <div>
                <p className={`font-semibold text-sm ${alert.severity === 'error' ? 'text-bne-crimson' : 'text-bne-amber'}`}>
                  {alert.title}
                </p>
                <p className="text-sm text-bne-steel mt-1">{alert.message}</p>
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
            <div className="text-center text-bne-crimson">
              <p className="font-semibold">Error loading data quality metrics</p>
              <p className="text-sm text-bne-steel mt-2">{statsError.message}</p>
            </div>
          </CardContent>
        </Card>
      </div>
    )
  }

  const { overview, freshness, quality, anomalies } = stats

  return (
    <div className="p-6 space-y-6">
      {/* Header */}
      <div>
        <h1 className="text-2xl font-bold text-bne-ink mb-2">Data Quality Monitoring</h1>
        <p className="text-bne-steel">Monitor data completeness, freshness, and quality across all sources</p>
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
          value={`${(quality.avg_quality_score * 100).toFixed(1)}%`}
          subtitle={`Based on ${quality.jobs_analyzed} jobs`}
          status={quality.avg_quality_score >= 0.7 ? 'excellent' : quality.avg_quality_score >= 0.5 ? 'good' : 'warning'}
        />
        <MetricCard
          title="Data Completeness"
          value={`${quality.avg_completeness}%`}
          subtitle="Average across all sources"
          status={quality.avg_completeness >= 90 ? 'excellent' : quality.avg_completeness >= 70 ? 'good' : 'warning'}
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
            <div className="text-center py-12 text-bne-steel">
              <p>No data sources configured</p>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  )
}

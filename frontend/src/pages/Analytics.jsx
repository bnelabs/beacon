import { useState, useMemo } from 'react'
import Card, { CardHeader, CardTitle, CardContent } from '../components/ui/Card'
import Badge from '../components/ui/Badge'
import LoadingSpinner from '../components/ui/LoadingSpinner'
import {
  useAnalyticsOverview,
  useTimeSeriesTrends,
  useAnomalyInsights
} from '../hooks/useAnalytics'

function MetricCard({ title, value, subtitle, trend, icon, color = 'bne-azure' }) {
  return (
    <Card>
      <CardContent className="p-6">
        <div className="flex items-start justify-between mb-3">
          <div className={`p-3 rounded-lg bg-${color}/10`}>
            {icon}
          </div>
          {trend && (
            <div className={`flex items-center gap-1 text-sm font-medium ${trend > 0 ? 'text-bne-emerald' : 'text-bne-crimson'}`}>
              {trend > 0 ? (
                <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 7h8m0 0v8m0-8l-8 8-4-4-6 6" />
                </svg>
              ) : (
                <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 17h8m0 0V9m0 8l-8-8-4 4-6-6" />
                </svg>
              )}
              {Math.abs(trend)}%
            </div>
          )}
        </div>
        <div>
          <h3 className="text-sm font-medium text-bne-steel mb-1">{title}</h3>
          <div className="text-3xl font-bold text-bne-ink mb-1">{value}</div>
          {subtitle && <p className="text-sm text-bne-steel">{subtitle}</p>}
        </div>
      </CardContent>
    </Card>
  )
}

function TimeSeriesChart({ data, metric }) {
  const maxValue = useMemo(() => {
    if (!data || data.length === 0) return 1
    return Math.max(...data.map(d => d.value || 0), 1)
  }, [data])

  const minValue = useMemo(() => {
    if (!data || data.length === 0) return 0
    return Math.min(...data.map(d => d.value || 0))
  }, [data])

  if (!data || data.length === 0) {
    return (
      <div className="text-center py-12 text-bne-steel">
        <p>No data available for the selected period</p>
      </div>
    )
  }

  const displayData = data.slice(-20) // Show last 20 data points

  return (
    <div className="space-y-4">
      {/* Line chart */}
      <div className="h-64 relative">
        <svg className="w-full h-full" viewBox="0 0 800 200" preserveAspectRatio="none">
          {/* Grid lines */}
          {[0, 25, 50, 75, 100].map((percent) => (
            <line
              key={percent}
              x1="0"
              y1={200 - (percent / 100) * 200}
              x2="800"
              y2={200 - (percent / 100) * 200}
              stroke="#e5e7eb"
              strokeWidth="1"
            />
          ))}

          {/* Data line */}
          <polyline
            points={displayData.map((point, index) => {
              const x = (index / (displayData.length - 1)) * 800
              const normalized = (point.value - minValue) / (maxValue - minValue || 1)
              const y = 200 - normalized * 180 - 10
              return `${x},${y}`
            }).join(' ')}
            fill="none"
            stroke="#2563eb"
            strokeWidth="3"
            strokeLinecap="round"
            strokeLinejoin="round"
          />

          {/* Data points */}
          {displayData.map((point, index) => {
            const x = (index / (displayData.length - 1)) * 800
            const normalized = (point.value - minValue) / (maxValue - minValue || 1)
            const y = 200 - normalized * 180 - 10
            return (
              <circle
                key={index}
                cx={x}
                cy={y}
                r="4"
                fill="#2563eb"
                className="hover:r-6 transition-all cursor-pointer"
              >
                <title>{`${point.date}: ${point.value?.toFixed(4) || 'N/A'}`}</title>
              </circle>
            )
          })}
        </svg>

        {/* Y-axis labels */}
        <div className="absolute left-0 top-0 h-full flex flex-col justify-between text-xs text-bne-steel pr-2">
          <span>{maxValue.toFixed(2)}</span>
          <span>{(minValue + (maxValue - minValue) / 2).toFixed(2)}</span>
          <span>{minValue.toFixed(2)}</span>
        </div>
      </div>

      {/* X-axis labels */}
      <div className="flex justify-between text-xs text-bne-steel">
        {displayData.filter((_, i) => i % Math.ceil(displayData.length / 5) === 0).map((point) => (
          <span key={point.date}>
            {new Date(point.date).toLocaleDateString('en-US', { month: 'short', day: 'numeric' })}
          </span>
        ))}
      </div>

      {/* Statistics */}
      <div className="grid grid-cols-4 gap-4 pt-4 border-t border-bne-frost">
        <div>
          <div className="text-xs text-bne-steel">Latest</div>
          <div className="text-lg font-semibold text-bne-ink">{data[data.length - 1]?.value?.toFixed(4) || 'N/A'}</div>
        </div>
        <div>
          <div className="text-xs text-bne-steel">Average</div>
          <div className="text-lg font-semibold text-bne-ink">
            {(data.reduce((sum, d) => sum + (d.value || 0), 0) / data.length).toFixed(4)}
          </div>
        </div>
        <div>
          <div className="text-xs text-bne-steel">Maximum</div>
          <div className="text-lg font-semibold text-bne-emerald">{maxValue.toFixed(4)}</div>
        </div>
        <div>
          <div className="text-xs text-bne-steel">Minimum</div>
          <div className="text-lg font-semibold text-bne-crimson">{minValue.toFixed(4)}</div>
        </div>
      </div>
    </div>
  )
}

function AnomalyAlerts({ anomalies }) {
  const getSeverityColor = (severity) => {
    switch (severity) {
      case 'high': return 'bg-bne-crimson/10 border-bne-crimson/20 text-bne-crimson'
      case 'medium': return 'bg-bne-amber/10 border-bne-amber/20 text-bne-amber'
      default: return 'bg-bne-azure/10 border-bne-azure/20 text-bne-azure'
    }
  }

  const getSeverityIcon = (severity) => {
    if (severity === 'high') {
      return (
        <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
        </svg>
      )
    }
    return (
      <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
      </svg>
    )
  }

  if (!anomalies || anomalies.length === 0) {
    return (
      <div className="flex items-center justify-center py-8 text-bne-emerald">
        <svg className="w-12 h-12 mr-3" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" />
        </svg>
        <div>
          <p className="font-semibold text-bne-ink">All Systems Normal</p>
          <p className="text-sm text-bne-steel">No anomalies detected</p>
        </div>
      </div>
    )
  }

  return (
    <div className="space-y-3">
      {anomalies.map((anomaly, index) => (
        <div
          key={index}
          className={`flex items-start gap-3 p-4 rounded-lg border ${getSeverityColor(anomaly.severity)}`}
        >
          <div className="flex-shrink-0 mt-0.5">
            {getSeverityIcon(anomaly.severity)}
          </div>
          <div className="flex-1">
            <div className="flex items-center gap-2 mb-1">
              <Badge variant={anomaly.severity === 'high' ? 'danger' : 'warning'} size="sm">
                {anomaly.severity.toUpperCase()}
              </Badge>
              <span className="text-sm font-medium">{anomaly.type.replace(/_/g, ' ').toUpperCase()}</span>
            </div>
            <p className="text-sm">{anomaly.message}</p>
            <div className="mt-2 text-xs opacity-75">
              Detected: {new Date(anomaly.detected_at).toLocaleString()}
            </div>
          </div>
        </div>
      ))}
    </div>
  )
}

function JobDistributionChart({ distribution }) {
  const total = Object.values(distribution).reduce((sum, count) => sum + count, 0)

  if (total === 0) {
    return <div className="text-center py-8 text-bne-steel">No job data available</div>
  }

  return (
    <div className="space-y-3">
      {Object.entries(distribution).map(([jobType, count]) => {
        const percentage = (count / total) * 100

        return (
          <div key={jobType} className="space-y-1">
            <div className="flex items-center justify-between text-sm">
              <span className="font-medium text-bne-ink">{jobType.replace(/_/g, ' ')}</span>
              <span className="text-bne-steel">{count} ({percentage.toFixed(1)}%)</span>
            </div>
            <div className="w-full h-3 bg-bne-frost rounded-full overflow-hidden">
              <div
                className="h-full bg-gradient-to-r from-bne-azure to-bne-indigo rounded-full transition-all"
                style={{ width: `${percentage}%` }}
              />
            </div>
          </div>
        )
      })}
    </div>
  )
}

export default function Analytics() {
  const [timePeriod, setTimePeriod] = useState(30)
  const [selectedMetric, setSelectedMetric] = useState('quality')

  const { data: overview, isLoading: overviewLoading, error: overviewError } = useAnalyticsOverview(timePeriod)
  const { data: trendsData, isLoading: trendsLoading } = useTimeSeriesTrends(selectedMetric, timePeriod)
  const { data: anomaliesData, isLoading: anomaliesLoading } = useAnomalyInsights(7)

  if (overviewLoading || trendsLoading || anomaliesLoading) {
    return (
      <div className="flex items-center justify-center h-[60vh]">
        <LoadingSpinner message="Loading analytics..." />
      </div>
    )
  }

  if (overviewError) {
    return (
      <div className="p-6">
        <Card>
          <CardContent className="p-6">
            <div className="text-center text-bne-crimson">
              <p className="font-semibold">Error loading analytics</p>
              <p className="text-sm text-bne-steel mt-2">{overviewError.message}</p>
            </div>
          </CardContent>
        </Card>
      </div>
    )
  }

  const { jobs, models, data_quality } = overview || { jobs: {}, models: {}, data_quality: {} }

  return (
    <div className="p-6 space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-bne-ink mb-2">Advanced Analytics</h1>
          <p className="text-bne-steel">Comprehensive insights and trends across the platform</p>
        </div>
        <div className="flex items-center gap-2">
          {[7, 14, 30, 60].map((days) => (
            <button
              key={days}
              onClick={() => setTimePeriod(days)}
              className={`px-4 py-2 rounded-lg text-sm font-medium transition-colors ${
                timePeriod === days
                  ? 'bg-bne-azure text-white'
                  : 'bg-bne-ice text-bne-steel hover:bg-bne-frost'
              }`}
            >
              {days}d
            </button>
          ))}
        </div>
      </div>

      {/* Summary Metrics */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
        <MetricCard
          title="Total Jobs"
          value={jobs.total || 0}
          subtitle={`${jobs.completed || 0} completed`}
          icon={
            <svg className="w-6 h-6 text-bne-azure" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2" />
            </svg>
          }
          color="bne-azure"
        />
        <MetricCard
          title="Success Rate"
          value={`${jobs.success_rate || 0}%`}
          subtitle={`${jobs.failed || 0} failed jobs`}
          icon={
            <svg className="w-6 h-6 text-bne-emerald" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" />
            </svg>
          }
          color="bne-emerald"
        />
        <MetricCard
          title="Model Health"
          value={`${models.health_percentage || 0}%`}
          subtitle={`${models.ready || 0}/${models.total || 0} models ready`}
          icon={
            <svg className="w-6 h-6 text-bne-indigo" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z" />
            </svg>
          }
          color="bne-indigo"
        />
        <MetricCard
          title="Avg Execution Time"
          value={`${jobs.avg_execution_time || 0}s`}
          subtitle="Per completed job"
          icon={
            <svg className="w-6 h-6 text-bne-amber" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" />
            </svg>
          }
          color="bne-amber"
        />
      </div>

      {/* Anomaly Alerts */}
      <Card>
        <CardHeader>
          <div className="flex items-center justify-between">
            <CardTitle>Anomaly Detection (Last 7 Days)</CardTitle>
            <Badge variant={anomaliesData?.anomalies_detected > 0 ? 'danger' : 'success'}>
              {anomaliesData?.anomalies_detected || 0} detected
            </Badge>
          </div>
        </CardHeader>
        <CardContent>
          <AnomalyAlerts anomalies={anomaliesData?.anomalies || []} />
        </CardContent>
      </Card>

      {/* Time Series Trends */}
      <Card>
        <CardHeader>
          <div className="flex items-center justify-between">
            <CardTitle>Trends Over Time</CardTitle>
            <div className="flex gap-2">
              {[
                { value: 'quality', label: 'Data Quality' },
                { value: 'completeness', label: 'Completeness' },
                { value: 'jobs', label: 'Job Success' }
              ].map(({ value, label }) => (
                <button
                  key={value}
                  onClick={() => setSelectedMetric(value)}
                  className={`px-3 py-1 rounded text-sm font-medium transition-colors ${
                    selectedMetric === value
                      ? 'bg-bne-azure text-white'
                      : 'bg-bne-ice text-bne-steel hover:bg-bne-frost'
                  }`}
                >
                  {label}
                </button>
              ))}
            </div>
          </div>
        </CardHeader>
        <CardContent>
          <TimeSeriesChart data={trendsData?.series || []} metric={selectedMetric} />
        </CardContent>
      </Card>

      {/* Job Distribution and Data Quality */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <Card>
          <CardHeader>
            <CardTitle>Job Type Distribution</CardTitle>
          </CardHeader>
          <CardContent>
            <JobDistributionChart distribution={jobs.distribution || {}} />
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Data Quality Metrics</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="space-y-4">
              <div className="p-4 bg-bne-ice rounded-lg">
                <div className="text-sm text-bne-steel mb-1">Average Quality Score</div>
                <div className="text-3xl font-bold text-bne-ink">{data_quality.avg_quality_score?.toFixed(4) || 'N/A'}</div>
                <div className="mt-2 w-full h-2 bg-bne-frost rounded-full overflow-hidden">
                  <div
                    className="h-full bg-gradient-to-r from-bne-azure to-bne-emerald rounded-full"
                    style={{ width: `${(data_quality.avg_quality_score || 0) * 100}%` }}
                  />
                </div>
              </div>

              <div className="p-4 bg-bne-ice rounded-lg">
                <div className="text-sm text-bne-steel mb-1">Average Completeness</div>
                <div className="text-3xl font-bold text-bne-ink">{((data_quality.avg_completeness || 0) * 100).toFixed(1)}%</div>
                <div className="mt-2 w-full h-2 bg-bne-frost rounded-full overflow-hidden">
                  <div
                    className="h-full bg-gradient-to-r from-bne-indigo to-bne-azure rounded-full"
                    style={{ width: `${(data_quality.avg_completeness || 0) * 100}%` }}
                  />
                </div>
              </div>

              <div className="grid grid-cols-2 gap-4">
                <div className="p-3 bg-white rounded-lg border border-bne-frost">
                  <div className="text-xs text-bne-steel">Jobs Analyzed</div>
                  <div className="text-2xl font-bold text-bne-ink">{data_quality.jobs_analyzed || 0}</div>
                </div>
                <div className="p-3 bg-white rounded-lg border border-bne-frost">
                  <div className="text-xs text-bne-steel">Period</div>
                  <div className="text-2xl font-bold text-bne-ink">{timePeriod}d</div>
                </div>
              </div>
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  )
}

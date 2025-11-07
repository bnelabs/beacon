import { useQuery } from '@tanstack/react-query'

const API_BASE = '/api'

async function fetchApi(endpoint, options = {}) {
  const response = await fetch(`${API_BASE}${endpoint}`, {
    headers: {
      'Content-Type': 'application/json',
      ...options.headers
    },
    ...options
  })

  if (!response.ok) {
    const errorPayload = await response.json().catch(() => ({ detail: 'Request failed' }))
    const detail = errorPayload.detail
    let message

    if (typeof detail === 'string') {
      message = detail
    } else if (detail?.user_friendly) {
      message = detail.user_friendly
    } else {
      message = `HTTP ${response.status}`
    }

    throw new Error(message)
  }

  return response.json()
}

/**
 * Hook to fetch analytics overview
 */
export function useAnalyticsOverview(days = 30) {
  return useQuery({
    queryKey: ['analytics', 'overview', days],
    queryFn: () => fetchApi(`/v1/analytics/overview?days=${days}`),
    staleTime: 60000, // 1 minute
    refetchInterval: 120000 // Refetch every 2 minutes
  })
}

/**
 * Hook to fetch time-series trends
 */
export function useTimeSeriesTrends(metric = 'quality', days = 30) {
  return useQuery({
    queryKey: ['analytics', 'trends', metric, days],
    queryFn: () => fetchApi(`/v1/analytics/trends/time-series?metric=${metric}&days=${days}`),
    staleTime: 60000,
    refetchInterval: 120000
  })
}

/**
 * Hook to fetch model performance comparison
 */
export function useModelPerformanceComparison() {
  return useQuery({
    queryKey: ['analytics', 'models', 'comparison'],
    queryFn: () => fetchApi('/v1/analytics/models/performance-comparison'),
    staleTime: 120000, // 2 minutes
    refetchInterval: 300000 // Refetch every 5 minutes
  })
}

/**
 * Hook to fetch risk score distribution
 */
export function useRiskScoreDistribution(bins = 10) {
  return useQuery({
    queryKey: ['analytics', 'distribution', 'risk-scores', bins],
    queryFn: () => fetchApi(`/v1/analytics/distribution/risk-scores?bins=${bins}`),
    staleTime: 120000,
    refetchInterval: 300000
  })
}

/**
 * Hook to fetch anomaly insights
 */
export function useAnomalyInsights(days = 7) {
  return useQuery({
    queryKey: ['analytics', 'anomalies', days],
    queryFn: () => fetchApi(`/v1/analytics/insights/anomalies?days=${days}`),
    staleTime: 30000, // 30 seconds for quick anomaly detection
    refetchInterval: 60000 // Refetch every minute
  })
}

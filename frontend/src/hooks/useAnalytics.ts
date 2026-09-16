import { useQuery } from '@tanstack/react-query'
import { fetchApi } from '../utils/apiClient'
import type { AnalyticsOverview, AnomalyInsightsPayload, TimeSeriesPayload } from '../types/api'

// Dead-export note: useModelPerformanceComparison and useRiskScoreDistribution
// were removed here (no caller in src/ — checked by
// scripts/check_frontend_hook_reachability.mjs in CI). The endpoints remain
// documented in docs/api-endpoints.md; a hook re-added for a real screen
// should be typed against them.

/**
 * Hook to fetch analytics overview
 */
export function useAnalyticsOverview(days: number = 30) {
  return useQuery({
    queryKey: ['analytics', 'overview', days],
    queryFn: () => fetchApi<AnalyticsOverview>(`/v1/analytics/overview?days=${days}`),
    staleTime: 60000, // 1 minute
    refetchInterval: 120000 // Refetch every 2 minutes
  })
}

/**
 * Hook to fetch time-series trends
 */
export function useTimeSeriesTrends(metric: string = 'quality', days: number = 30) {
  return useQuery({
    queryKey: ['analytics', 'trends', metric, days],
    queryFn: () => fetchApi<TimeSeriesPayload>(`/v1/analytics/trends/time-series?metric=${metric}&days=${days}`),
    staleTime: 60000,
    refetchInterval: 120000
  })
}

/**
 * Hook to fetch anomaly insights
 */
export function useAnomalyInsights(days: number = 7) {
  return useQuery({
    queryKey: ['analytics', 'anomalies', days],
    queryFn: () => fetchApi<AnomalyInsightsPayload>(`/v1/analytics/insights/anomalies?days=${days}`),
    staleTime: 30000, // 30 seconds for quick anomaly detection
    refetchInterval: 60000 // Refetch every minute
  })
}

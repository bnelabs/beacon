import { useQuery } from '@tanstack/react-query'
import { fetchApi } from '../utils/apiClient'
import type { DataQualityStats, QualityTrendsPayload, SourceQualityRow } from '../types/api'

/**
 * Hook to fetch data quality statistics
 */
export function useDataQualityStats() {
  return useQuery({
    queryKey: ['dataQuality', 'stats'],
    queryFn: () => fetchApi<DataQualityStats>('/v1/data-quality/stats'),
    staleTime: 30000, // 30 seconds
    refetchInterval: 60000 // Refetch every minute
  })
}

/**
 * Hook to fetch source quality details
 */
export function useSourceQualityDetails() {
  return useQuery({
    queryKey: ['dataQuality', 'sources'],
    queryFn: () => fetchApi<SourceQualityRow[]>('/v1/data-quality/sources'),
    staleTime: 30000,
    refetchInterval: 60000
  })
}

/**
 * Hook to fetch quality trends
 */
export function useQualityTrends(days: number = 30) {
  return useQuery({
    queryKey: ['dataQuality', 'trends', days],
    queryFn: () => fetchApi<QualityTrendsPayload>(`/v1/data-quality/trends?days=${days}`),
    staleTime: 60000, // 1 minute
    refetchInterval: 120000 // Refetch every 2 minutes
  })
}

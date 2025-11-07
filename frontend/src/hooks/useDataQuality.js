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
 * Hook to fetch data quality statistics
 */
export function useDataQualityStats() {
  return useQuery({
    queryKey: ['dataQuality', 'stats'],
    queryFn: () => fetchApi('/v1/data-quality/stats'),
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
    queryFn: () => fetchApi('/v1/data-quality/sources'),
    staleTime: 30000,
    refetchInterval: 60000
  })
}

/**
 * Hook to fetch quality trends
 */
export function useQualityTrends(days = 30) {
  return useQuery({
    queryKey: ['dataQuality', 'trends', days],
    queryFn: () => fetchApi(`/v1/data-quality/trends?days=${days}`),
    staleTime: 60000, // 1 minute
    refetchInterval: 120000 // Refetch every 2 minutes
  })
}

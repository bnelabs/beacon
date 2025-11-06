import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'

const API_BASE = import.meta.env.VITE_API_BASE_URL || 'http://localhost:3456'

// Fetch countries with filters
export function useCountries(filters = {}) {
  const params = new URLSearchParams()

  if (filters.search) params.append('search', filters.search)
  if (filters.region) params.append('region', filters.region)
  if (filters.risk_level) params.append('risk_level', filters.risk_level)
  if (filters.min_gdp) params.append('min_gdp', filters.min_gdp)
  if (filters.max_gdp) params.append('max_gdp', filters.max_gdp)
  if (filters.min_population) params.append('min_population', filters.min_population)
  if (filters.has_banking_data !== null && filters.has_banking_data !== undefined) {
    params.append('has_banking_data', filters.has_banking_data)
  }

  const queryString = params.toString()
  const url = `${API_BASE}/api/v1/countries/${queryString ? `?${queryString}` : ''}`

  return useQuery({
    queryKey: ['countries', filters],
    queryFn: async () => {
      const response = await fetch(url)
      if (!response.ok) {
        throw new Error('Failed to fetch countries')
      }
      return response.json()
    },
    staleTime: 5 * 60 * 1000, // 5 minutes
  })
}

// Fetch single country
export function useCountry(countryCode) {
  return useQuery({
    queryKey: ['country', countryCode],
    queryFn: async () => {
      const response = await fetch(`${API_BASE}/api/v1/countries/${countryCode}`)
      if (!response.ok) {
        throw new Error('Failed to fetch country')
      }
      return response.json()
    },
    enabled: !!countryCode,
    staleTime: 5 * 60 * 1000,
  })
}

// Fetch country indicators
export function useCountryIndicators(countryCode, options = {}) {
  const params = new URLSearchParams()

  if (options.category) params.append('category', options.category)
  if (options.indicator_code) params.append('indicator_code', options.indicator_code)
  if (options.start_year) params.append('start_year', options.start_year)
  if (options.end_year) params.append('end_year', options.end_year)

  const queryString = params.toString()
  const url = `${API_BASE}/api/v1/countries/${countryCode}/indicators${queryString ? `?${queryString}` : ''}`

  return useQuery({
    queryKey: ['country-indicators', countryCode, options],
    queryFn: async () => {
      const response = await fetch(url)
      if (!response.ok) {
        throw new Error('Failed to fetch indicators')
      }
      return response.json()
    },
    enabled: !!countryCode,
    staleTime: 10 * 60 * 1000, // 10 minutes
  })
}

// Compare countries
export function useCountryComparison() {
  return useMutation({
    mutationFn: async (request) => {
      const response = await fetch(`${API_BASE}/api/v1/countries/compare`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify(request),
      })
      if (!response.ok) {
        throw new Error('Failed to compare countries')
      }
      return response.json()
    },
  })
}

// Sync from World Bank
export function useCountrySync() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: async (request) => {
      const response = await fetch(`${API_BASE}/api/v1/countries/sync`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify(request),
      })
      if (!response.ok) {
        const error = await response.json()
        throw new Error(error.detail || 'Failed to sync country data')
      }
      return response.json()
    },
    onSuccess: () => {
      // Invalidate countries queries to refetch
      queryClient.invalidateQueries({ queryKey: ['countries'] })
    },
  })
}

// Fetch regions list
export function useRegions() {
  return useQuery({
    queryKey: ['regions'],
    queryFn: async () => {
      const response = await fetch(`${API_BASE}/api/v1/countries/regions/list`)
      if (!response.ok) {
        throw new Error('Failed to fetch regions')
      }
      return response.json()
    },
    staleTime: 60 * 60 * 1000, // 1 hour
  })
}

// Fetch risk levels summary
export function useRiskLevelsSummary() {
  return useQuery({
    queryKey: ['risk-levels-summary'],
    queryFn: async () => {
      const response = await fetch(`${API_BASE}/api/v1/countries/risk-levels/summary`)
      if (!response.ok) {
        throw new Error('Failed to fetch risk levels summary')
      }
      return response.json()
    },
    staleTime: 10 * 60 * 1000, // 10 minutes
  })
}

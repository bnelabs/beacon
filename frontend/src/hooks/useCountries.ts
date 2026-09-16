import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'

// Defaults to the SAME ORIGIN (empty base), not to http://localhost:3456.
// The bundled nginx proxies /api/ to the backend container, so a relative base
// works for every host that can reach the frontend -- which is what makes the
// stack usable from another machine on the LAN. Hard-coding localhost:3456 baked
// the *build* machine's idea of the backend into the bundle and then resolved it
// against the *browser's* localhost, so a remote browser silently called itself.
import { API_ORIGIN, fetchApi, fetchJson } from '../utils/apiClient'

// Set VITE_API_BASE_URL only to point at a genuinely different origin.

/** Query filters for the country list endpoint. */
export interface CountryFilters {
  search?: string
  region?: string
  risk_level?: string
  min_gdp?: string | number
  max_gdp?: string | number
  min_population?: string | number
  has_banking_data?: boolean | string | null
}

/** Query filters for a single country's indicator series. */
export interface CountryIndicatorOptions {
  category?: string
  indicator_code?: string
  start_year?: string | number
  end_year?: string | number
}

// Fetch countries with filters
export function useCountries(filters: CountryFilters = {}) {
  const params = new URLSearchParams()

  if (filters.search) params.append('search', filters.search)
  if (filters.region) params.append('region', filters.region)
  if (filters.risk_level) params.append('risk_level', filters.risk_level)
  if (filters.min_gdp) params.append('min_gdp', String(filters.min_gdp))
  if (filters.max_gdp) params.append('max_gdp', String(filters.max_gdp))
  if (filters.min_population) params.append('min_population', String(filters.min_population))
  if (filters.has_banking_data !== null && filters.has_banking_data !== undefined) {
    params.append('has_banking_data', String(filters.has_banking_data))
  }

  const queryString = params.toString()
  const url = `${API_ORIGIN}/api/v1/countries/${queryString ? `?${queryString}` : ''}`

  return useQuery({
    queryKey: ['countries', filters],
    queryFn: async () => {
      return fetchJson(url)
    },
    staleTime: 5 * 60 * 1000, // 5 minutes
  })
}

// Fetch single country
export function useCountry(countryCode?: string) {
  return useQuery({
    queryKey: ['country', countryCode],
    queryFn: async () => {
      return fetchJson(`${API_ORIGIN}/api/v1/countries/${countryCode}`)
    },
    enabled: !!countryCode,
    staleTime: 5 * 60 * 1000,
  })
}

// Fetch country indicators
export function useCountryIndicators(countryCode?: string, options: CountryIndicatorOptions = {}) {
  const params = new URLSearchParams()

  if (options.category) params.append('category', options.category)
  if (options.indicator_code) params.append('indicator_code', options.indicator_code)
  if (options.start_year) params.append('start_year', String(options.start_year))
  if (options.end_year) params.append('end_year', String(options.end_year))

  const queryString = params.toString()
  const url = `${API_ORIGIN}/api/v1/countries/${countryCode}/indicators${queryString ? `?${queryString}` : ''}`

  return useQuery({
    queryKey: ['country-indicators', countryCode, options],
    queryFn: async () => {
      return fetchJson(url)
    },
    enabled: !!countryCode,
    staleTime: 10 * 60 * 1000, // 10 minutes
  })
}

// Compare countries
export function useCountryComparison() {
  return useMutation({
    mutationFn: async (request: unknown) => {
      return fetchApi('/v1/countries/compare', {
        method: 'POST',
        body: JSON.stringify(request)
      })
    },
  })
}

// Sync from World Bank
export function useCountrySync() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: async (request: unknown) => {
      return fetchApi('/v1/countries/sync', {
        method: 'POST',
        body: JSON.stringify(request)
      })
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
      return fetchJson(`${API_ORIGIN}/api/v1/countries/regions/list`)
    },
    staleTime: 60 * 60 * 1000, // 1 hour
  })
}

// Fetch risk levels summary
export function useRiskLevelsSummary() {
  return useQuery({
    queryKey: ['risk-levels-summary'],
    queryFn: async () => {
      return fetchJson(`${API_ORIGIN}/api/v1/countries/risk-levels/summary`)
    },
    staleTime: 10 * 60 * 1000, // 10 minutes
  })
}

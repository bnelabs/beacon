import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'

const API_BASE_URL = '/api'

async function fetchApi(endpoint, options = {}) {
  const response = await fetch(`${API_BASE_URL}${endpoint}`, {
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
    } else if (detail?.technical) {
      message = detail.technical
    } else if (detail) {
      try {
        message = JSON.stringify(detail)
      } catch (error) {
        message = 'Request failed'
      }
    } else {
      message = `HTTP ${response.status}`
    }

    throw new Error(message)
  }

  return response.json()
}

function buildQueryString(params = {}) {
  const query = new URLSearchParams()

  if (params.category) query.set('category', params.category)
  if (params.region) query.set('region', params.region)
  if (params.countries?.length) query.set('countries', params.countries.join(','))
  if (params.sources?.length) query.set('sources', params.sources.join(','))
  if (params.risk_type) query.set('risk_type', params.risk_type)
  if (params.search) query.set('search', params.search)

  if (typeof params.enabled_only === 'boolean') query.set('enabled_only', String(params.enabled_only))
  if (typeof params.default_only === 'boolean') query.set('default_only', String(params.default_only))

  const qs = query.toString()
  return qs ? `?${qs}` : ''
}

export function useJobs() {
  return useQuery({
    queryKey: ['jobs'],
    queryFn: () => fetchApi('/v1/jobs')
  })
}

export function useJob(jobId) {
  return useQuery({
    queryKey: ['jobs', jobId],
    queryFn: () => fetchApi(`/v1/jobs/${jobId}`),
    enabled: !!jobId
  })
}

export function useModels() {
  return useQuery({
    queryKey: ['models'],
    queryFn: () => fetchApi('/models')
  })
}

export function useModel(modelId) {
  return useQuery({
    queryKey: ['models', modelId],
    queryFn: () => fetchApi(`/models/${modelId}`),
    enabled: !!modelId
  })
}

export function useDataSources() {
  return useQuery({
    queryKey: ['dataSources'],
    queryFn: () => fetchApi('/v1/data-sources'),
    staleTime: 300_000
  })
}

export function useCreateJob() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: (data) =>
      fetchApi('/v1/jobs', {
        method: 'POST',
        body: JSON.stringify(data)
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['jobs'] })
    }
  })
}

export function useCancelJob() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: (jobId) =>
      fetchApi(`/v1/jobs/${jobId}/cancel`, {
        method: 'POST'
      }),
    onSuccess: (_, jobId) => {
      queryClient.invalidateQueries({ queryKey: ['jobs', jobId] })
      queryClient.invalidateQueries({ queryKey: ['jobs'] })
    }
  })
}

export function useBatchCancelJobs() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: (jobIds) =>
      fetchApi('/v1/jobs/batch/cancel', {
        method: 'POST',
        body: JSON.stringify({ job_ids: jobIds })
      }),
    onSuccess: (result) => {
      // Invalidate all affected job queries
      result.cancelled.forEach(jobId => {
        queryClient.invalidateQueries({ queryKey: ['jobs', jobId] })
      })
      queryClient.invalidateQueries({ queryKey: ['jobs'] })
    }
  })
}

export function useSyncDataSource() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: ({ sourceId }) =>
      fetchApi(`/v1/data-sources/${sourceId}/sync`, {
        method: 'POST'
      }),
    onMutate: async ({ sourceId }) => {
      await queryClient.cancelQueries({ queryKey: ['dataSources'] })
      const previous = queryClient.getQueryData(['dataSources'])
      if (previous) {
        queryClient.setQueryData(['dataSources'], old =>
          old?.map(source =>
            (source.id || source.source_id) === sourceId
              ? { ...source, status: 'syncing' }
              : source
          )
        )
      }
      return { previous }
    },
    onSuccess: (updated) => {
      if (!updated) {
        return
      }
      const updatedId = updated.id ?? updated.source_id
      if (!updatedId) {
        return
      }
      queryClient.setQueryData(['dataSources'], old =>
        old?.map(source => {
          const sourceId = source.id ?? source.source_id
          if (sourceId === updatedId) {
            return { ...source, ...updated }
          }
          return source
        }) ?? old
      )
    },
    onError: (_error, _variables, context) => {
      if (context?.previous) {
        queryClient.setQueryData(['dataSources'], context.previous)
      }
    },
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: ['dataSources'] })
    }
  })
}

export function useCreateDataSource() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: (payload) =>
      fetchApi('/v1/data-sources', {
        method: 'POST',
        body: JSON.stringify(payload)
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['dataSources'] })
    }
  })
}

export function useUpdateDataSource() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: ({ sourceId, data }) =>
      fetchApi(`/v1/data-sources/${sourceId}`, {
        method: 'PUT',
        body: JSON.stringify(data)
      }),
    onSuccess: (_data, variables) => {
      const sourceId = variables?.sourceId
      queryClient.invalidateQueries({ queryKey: ['dataSources'] })
      if (sourceId) {
        queryClient.invalidateQueries({ queryKey: ['dataSources', sourceId] })
      }
    }
  })
}

export function useCatalogueItems(filters = {}, options = {}) {
  const queryKey = ['catalogue', filters]
  const enabled = options.enabled ?? true

  return useQuery({
    queryKey,
    queryFn: () => fetchApi(`/v1/catalogue${buildQueryString(filters)}`),
    enabled,
    staleTime: options.staleTime ?? 60_000
  })
}

export function useJobDataQuality(jobId, options = {}) {
  return useQuery({
    queryKey: ['job', jobId, 'dataQuality'],
    queryFn: () => fetchApi(`/v1/results/${jobId}/data-quality`),
    enabled: Boolean(jobId) && (options.enabled ?? true),
    staleTime: options.staleTime ?? 60_000
  })
}

export function useBanksByRegion(filters) {
  return useQuery({
    queryKey: ['banks', filters],
    enabled: !!filters,
    queryFn: async () => {
      const data = await fetchApi(`/v1/catalogue${buildQueryString(filters)}`)
      return (data || []).map((item) => ({
        id: item.id,
        code: item.code,
        name: item.name,
        category: item.category,
        country: item.region,
        region: item.region,
        description: item.description,
        metadata: item.parameters || {},
        risk_score: item.metadata?.risk_score,
        source: item.data_source?.name || ''
      }))
    }
  })
}

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
    const error = await response.json().catch(() => ({ detail: 'Request failed' }))
    throw new Error(error.detail || `HTTP ${response.status}`)
  }

  return response.json()
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
    queryFn: () => fetchApi('/v1/models')
  })
}

export function useDataSources() {
  return useQuery({
    queryKey: ['dataSources'],
    queryFn: () => fetchApi('/v1/catalogue/sources'),
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

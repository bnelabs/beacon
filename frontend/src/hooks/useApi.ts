import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { fetchApi } from '../utils/apiClient'
import type {
  BankSummary,
  BatchCancelResult,
  CatalogueFilters,
  CatalogueItem,
  DataSource,
  DataSourceFormPayload,
  DataSourceHealthPayload,
  DataDisclosure,
  EntityId,
  Job,
  JobCreatePayload,
  JobDataQualityReport,
  ModelDetailData,
  ModelSummary,
  NetworkGraphPayload,
  NormalizedNetworkGraph,
  ProbeResult,
  SystemStatus,
  ValidationReport
} from '../types/api'

/** Shared options bag for queries that callers enable/stale-time per use. */
export interface QueryOptions {
  enabled?: boolean
  staleTime?: number
  refetchInterval?: number
}

function buildQueryString(params: CatalogueFilters = {}): string {
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
    queryFn: () => fetchApi<Job[]>('/v1/jobs')
  })
}

export function useJob(jobId?: EntityId | null) {
  return useQuery({
    queryKey: ['jobs', jobId],
    queryFn: () => fetchApi<Job>(`/v1/jobs/${jobId}`),
    enabled: !!jobId
  })
}

export function useModels() {
  return useQuery({
    queryKey: ['models'],
    queryFn: () => fetchApi<ModelSummary[]>('/models')
  })
}

export function useModel(modelId?: EntityId | null) {
  return useQuery({
    queryKey: ['models', modelId],
    queryFn: () => fetchApi<ModelDetailData>(`/models/${modelId}`),
    enabled: !!modelId
  })
}

export function useDataSources() {
  return useQuery({
    queryKey: ['dataSources'],
    queryFn: () => fetchApi<DataSource[]>('/v1/data-sources'),
    staleTime: 300_000
  })
}

export function useDataDisclosure() {
  return useQuery({
    queryKey: ['dataSources', 'disclosure'],
    queryFn: () => fetchApi<DataDisclosure>('/v1/data-sources/disclosure'),
    staleTime: 300_000
  })
}

export function useDataSourceHealth() {
  return useQuery({
    queryKey: ['dataSources', 'health'],
    queryFn: () => fetchApi<DataSourceHealthPayload>('/v1/data-sources/health'),
    staleTime: 60_000,
    refetchInterval: 60_000
  })
}

/** The id passed through to the probe URL; matches `source.id || source.source_id`
 *  at the call site, which can be missing for a malformed row. */
type SourceKey = EntityId | null | undefined

export function useProbeDataSource() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: (sourceId: SourceKey) =>
      fetchApi<ProbeResult>(`/v1/data-sources/${sourceId}/probe`, { method: 'POST' }),
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: ['dataSources'] })
      queryClient.invalidateQueries({ queryKey: ['dataSources', 'health'] })
    }
  })
}

/** PUT variables: `sourceId` selects the row, every remaining key is the body. */
export type UpdateDataSourceVars = { sourceId: SourceKey } & Record<string, unknown>

export function useUpdateDataSource() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: ({ sourceId, ...body }: UpdateDataSourceVars) =>
      fetchApi<DataSource>(`/v1/data-sources/${sourceId}`, {
        method: 'PUT',
        body: JSON.stringify(body)
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['dataSources'] })
      queryClient.invalidateQueries({ queryKey: ['dataSources', 'health'] })
    }
  })
}

export function useCreateJob() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: (data: JobCreatePayload) =>
      fetchApi<Job>('/v1/jobs', {
        method: 'POST',
        body: JSON.stringify(data)
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['jobs'] })
    }
  })
}

export function useRetryJob() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: (jobId: SourceKey) => fetchApi<Job>(`/v1/jobs/${jobId}/retry`, { method: 'POST' }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['jobs'] })
    }
  })
}

export function useCancelJob() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: (jobId: SourceKey) =>
      // The backend exposes single-job cancellation as DELETE /jobs/{id}
      // (the batch endpoint below is POST /jobs/batch/cancel). Calling
      // POST /jobs/{id}/cancel returned 405.
      fetchApi<null>(`/v1/jobs/${jobId}`, {
        method: 'DELETE'
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
    mutationFn: (jobIds: EntityId[]) =>
      fetchApi<BatchCancelResult>('/v1/jobs/batch/cancel', {
        method: 'POST',
        body: JSON.stringify({ job_ids: jobIds })
      }),
    onSuccess: (result) => {
      // Invalidate all affected job queries
      result?.cancelled?.forEach((jobId) => {
        queryClient.invalidateQueries({ queryKey: ['jobs', jobId] })
      })
      queryClient.invalidateQueries({ queryKey: ['jobs'] })
    }
  })
}

export function useSyncDataSource() {
  const queryClient = useQueryClient()

  return useMutation({
    // The sync endpoint answers 202 with a JobResponse (the queued
    // collection job), NOT a data source. The previous onSuccess merged
    // that job row into the cached source — a job's `status: pending`
    // landing on a source badge. The queued job is visible under Jobs; the
    // source row refreshes through onSettled's invalidation.
    mutationFn: ({ sourceId }: { sourceId: SourceKey }) =>
      fetchApi<Job>(`/v1/data-sources/${sourceId}/sync`, {
        method: 'POST'
      }),
    onMutate: async ({ sourceId }) => {
      await queryClient.cancelQueries({ queryKey: ['dataSources'] })
      const previous = queryClient.getQueryData<DataSource[]>(['dataSources'])
      if (previous) {
        queryClient.setQueryData<DataSource[]>(['dataSources'], (old) =>
          old?.map((source) =>
            source.id === sourceId
              ? { ...source, status: 'syncing' }
              : source
          )
        )
      }
      return { previous }
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
    mutationFn: (payload: DataSourceFormPayload) =>
      fetchApi<DataSource>('/v1/data-sources', {
        method: 'POST',
        body: JSON.stringify(payload)
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['dataSources'] })
    }
  })
}

export function useCatalogueItems(filters: CatalogueFilters = {}, options: QueryOptions = {}) {
  const queryKey = ['catalogue', filters]
  const enabled = options.enabled ?? true

  return useQuery({
    queryKey,
    queryFn: () => fetchApi<CatalogueItem[]>(`/v1/catalogue${buildQueryString(filters)}`),
    enabled,
    staleTime: options.staleTime ?? 60_000
  })
}

export function useJobDataQuality(jobId: EntityId | null | undefined, options: QueryOptions = {}) {
  return useQuery({
    queryKey: ['job', jobId, 'dataQuality'],
    queryFn: () => fetchApi<JobDataQualityReport>(`/v1/results/${jobId}/data-quality`),
    enabled: Boolean(jobId) && (options.enabled ?? true),
    staleTime: options.staleTime ?? 60_000
  })
}

export function useBanksByRegion(filters: CatalogueFilters | null) {
  return useQuery({
    queryKey: ['banks', filters],
    enabled: !!filters,
    queryFn: async (): Promise<BankSummary[]> => {
      const data = await fetchApi<CatalogueItem[]>(`/v1/catalogue${buildQueryString(filters ?? {})}`)
      return (data || []).map((item): BankSummary => ({
        id: item.id,
        code: item.code,
        name: item.name,
        category: item.category,
        country: item.region,
        region: item.region,
        description: item.description,
        // The catalogue schema sends no parameters/metadata blob, so the old
        // `(item.parameters ?? item.metadata)?.risk_score` read could only
        // ever yield null in production. Say so instead of implying a
        // channel that does not exist.
        risk_score: null,
        source: item.data_source?.name || ''
      }))
    }
  })
}

/**
 * The current interbank multiplex network graph.
 *
 * Interbank exposures change daily and are an obligation set, so they come from
 * the backend (`GET /api/v1/network/graph`) rather than from a bundled fixture.
 * The endpoint answers 200 with `status: "unavailable"` when no institution has
 * uploaded a bilateral exposure matrix; that is a first-class state, not an
 * error, so callers should render it as "no network available" and must not
 * substitute the static demo file.
 */
export function useNetworkGraph(options: QueryOptions = {}) {
  return useQuery({
    queryKey: ['network', 'graph'],
    queryFn: () => fetchApi<NetworkGraphPayload>('/v1/network/graph'),
    staleTime: options.staleTime ?? 30_000,
    enabled: options.enabled ?? true
  })
}

/**
 * Flatten an API network payload into the shape the map components render.
 *
 * Kept next to the hook so the unavailable/available distinction is decoded in
 * exactly one place; a component must never have to guess whether an empty
 * `edges` array means "no network" or "a network with no edges".
 */
export function normalizeNetworkGraph(
  payload?: NetworkGraphPayload | null
): NormalizedNetworkGraph {
  if (!payload || typeof payload !== 'object') {
    return {
      status: 'unavailable',
      asOf: null,
      generatedAt: null,
      source: null,
      reason: 'No network response was returned.',
      nodes: [],
      edges: [],
      layers: [],
      metadata: {}
    }
  }

  return {
    status: payload.status === 'available' ? 'available' : 'unavailable',
    asOf: payload.as_of ?? null,
    generatedAt: payload.generated_at ?? null,
    source: payload.source ?? null,
    reason: payload.unavailable_reason ?? null,
    nodes: Array.isArray(payload.nodes) ? payload.nodes : [],
    edges: Array.isArray(payload.edges) ? payload.edges : [],
    layers: Array.isArray(payload.layers) ? payload.layers : [],
    metadata:
      payload.metadata && typeof payload.metadata === 'object' ? payload.metadata : {}
  }
}

/**
 * Live system status from GET /api/v1/system/status (cpu/memory/gpu/disk).
 * The dashboard used to render hardcoded "Operational/Connected/Active"
 * badges — invented states. It now renders what the backend measured, and
 * an unreachable backend renders as unknown, not as green.
 */
export function useSystemStatus(options: QueryOptions = {}) {
  return useQuery({
    queryKey: ['systemStatus'],
    queryFn: () => fetchApi<SystemStatus>('/v1/system/status'),
    refetchInterval: options.refetchInterval ?? 30_000,
    retry: 1,
    ...options
  })
}

/**
 * Predictive-validity report for a backtest job (round P1).
 * Absence is a status ("not_validated"), never an error wall.
 */
export function useValidationReport(jobId?: EntityId | null) {
  return useQuery({
    queryKey: ['validation', jobId],
    queryFn: () => fetchApi<ValidationReport>(`/v2/reports/validation/${jobId}`),
    enabled: !!jobId
  })
}

import PageContainer from '../components/ui/PageContainer'
import Card, { CardHeader, CardTitle, CardContent, CardFooter } from '../components/ui/Card'
import Button from '../components/ui/Button'
import Badge, { type BadgeVariant } from '../components/ui/Badge'
import LoadingSpinner from '../components/ui/LoadingSpinner'
import ErrorMessage from '../components/ui/ErrorMessage'
import {
  useCreateDataSource,
  useDataDisclosure,
  useDataSourceHealth,
  useDataSources,
  useProbeDataSource,
  useSyncDataSource,
  useUpdateDataSource
} from '../hooks/useApi'
import { useMemo, useState } from 'react'
import DataSourceFormModal from '../components/data-sources/DataSourceFormModal'
import DataSourceDetailsModal from '../components/data-sources/DataSourceDetailsModal'
import JobCreationModal from '../components/jobs/JobCreationModal'
import type {
  DataSource,
  DataSourceFormPayload,
  DataSourceHealthRow,
  EntityId,
  ProbeResult,
  SelectedDataset
} from '../types/api'

// Provenance classes come from the backend disclosure payload; this map only
// decides how each class is rendered (badge variant + human label). The
// vocabulary is closed on the backend (PROVENANCE_CLASSES), so an unknown
// class falls back to the neutral badge rather than disappearing.
const PROVENANCE_CLASS_META: Record<string, { label: string; variant: BadgeVariant }> = {
  supervisory_published: { label: 'Supervisory', variant: 'primary' },
  official_statistics: { label: 'Official statistics', variant: 'info' },
  regulatory_filings: { label: 'Regulatory filings', variant: 'info' },
  market_observed: { label: 'Market observed', variant: 'default' },
  research_dataset: { label: 'Research dataset', variant: 'warning' },
  operator_declared: { label: 'Operator declared', variant: 'warning' },
  undisclosed: { label: 'Undisclosed', variant: 'danger' }
}

/** Stable string key for a source row: property keys are strings at runtime,
 *  and probe results / health rows are looked up by exactly this. */
function sourceKey(source: DataSource): string {
  return String(source.id || source.source_id || '')
}

interface DataSourceCardProps {
  source: DataSource
  onSync?: (source: DataSource) => void
  onConfigure?: (source: DataSource) => void
  onView?: (source: DataSource) => void
  isSyncing?: boolean
  health?: DataSourceHealthRow | null
  onProbe?: (source: DataSource) => void
  onSchedule?: (source: DataSource, minutes: number | null) => void
  probePending?: boolean
  probeResult?: ProbeResult | null
}

function DataSourceCard({
  source,
  onSync,
  onConfigure,
  onView,
  isSyncing = false,
  health = null,
  onProbe,
  onSchedule,
  probePending = false,
  probeResult = null
}: DataSourceCardProps) {
  const statusVariants: Record<string, BadgeVariant> = {
    active: 'success',
    inactive: 'default',
    error: 'danger',
    syncing: 'primary'
  }

  const lastUpdated =
    source.last_successful_fetch ||
    source.updated_at ||
    source.last_updated ||
    null

  return (
    <Card>
      <CardHeader>
        <div className="flex items-start justify-between">
          <div>
            <div className="flex items-center gap-2 mb-2">
              <CardTitle>{source.name || source.source_name}</CardTitle>
              <Badge variant={statusVariants[source.status ?? ''] || 'default'} size="sm">
                {source.status || 'active'}
              </Badge>
            </div>
            <p className="text-sm text-bne-muted">{source.description}</p>
          </div>
        </div>
      </CardHeader>

      <CardContent>
        <div className="space-y-3">
          <div className="flex items-center justify-between text-sm">
            <span className="text-bne-muted">Source Type</span>
            <span className="font-medium text-bne-ink uppercase">
              {source.plugin_name || source.plugin_type || source.type}
            </span>
          </div>
          <div className="flex items-center justify-between text-sm">
            <span className="text-bne-muted">Last Updated</span>
            <span className="font-medium text-bne-ink">
              {lastUpdated ? new Date(lastUpdated).toLocaleDateString() : 'Never'}
            </span>
          </div>
          <div className="flex items-center justify-between text-sm">
            <span className="text-bne-muted">Records</span>
            <span className="font-medium text-bne-ink">{source.record_count?.toLocaleString() || '-'}</span>
          </div>
          <div className="flex items-center justify-between text-sm">
            <span className="text-bne-muted">Schedule</span>
            <select
              aria-label={`Collection schedule for ${source.name ?? 'this source'}`}
              className="rounded-md border border-bne-line bg-bne-card px-2 py-1 text-xs font-medium text-bne-ink focus:border-bne-pine focus:outline-none"
              value={source.sync_interval_minutes ?? ''}
              onChange={(event) =>
                onSchedule?.(source, event.target.value === '' ? null : Number(event.target.value))
              }
            >
              <option value="">Manual only</option>
              <option value="15">Every 15 minutes</option>
              <option value="60">Hourly</option>
              <option value="360">Every 6 hours</option>
              <option value="1440">Daily</option>
            </select>
          </div>
          {health && (
            <>
              <div className="flex items-center justify-between text-sm">
                <span className="text-bne-muted">Last run</span>
                <span className="font-medium text-bne-ink">
                  {health.last_sync_started_at
                    ? `${new Date(health.last_sync_started_at).toLocaleString()}${
                        health.last_sync_duration_ms != null
                          ? ` · ${(health.last_sync_duration_ms / 1000).toFixed(1)}s`
                          : ''
                      }${
                        health.last_sync_rows != null
                          ? ` · ${health.last_sync_rows.toLocaleString()} rows`
                          : ''
                      }`
                    : 'Never'}
                </span>
              </div>
              <div className="flex items-center justify-between text-sm">
                <span className="text-bne-muted">Next refresh</span>
                {health.scheduled ? (
                  health.collection_running ? (
                    <Badge variant="primary" size="sm">running now</Badge>
                  ) : health.overdue ? (
                    <Badge variant="warning" size="sm">
                      {(health.consecutive_failures ?? 0) > 0
                        ? `overdue · retry ×${health.backoff_factor}`
                        : 'due'}
                    </Badge>
                  ) : (
                    <span className="font-medium text-bne-ink">
                      {health.next_due_at ? new Date(health.next_due_at).toLocaleString() : '—'}
                    </span>
                  )
                ) : (
                  <span className="font-medium text-bne-muted">manual</span>
                )}
              </div>
              {(health.consecutive_failures ?? 0) > 0 && health.error_message && (
                <p className="text-xs text-bne-clay">
                  {health.consecutive_failures} consecutive failure(s): {health.error_message}
                </p>
              )}
            </>
          )}
          {probeResult && (
            <p className={`text-xs ${probeResult.success ? 'text-bne-pine' : 'text-bne-clay'}`}>
              {probeResult.success ? 'Reachable:' : 'Unreachable:'} {probeResult.message}
            </p>
          )}
          {source.api_endpoint && (
            <div className="flex items-center justify-between text-sm">
              <span className="text-bne-muted">Endpoint</span>
              <span className="font-mono text-xs text-bne-ink truncate max-w-[200px]">
                {source.api_endpoint}
              </span>
            </div>
          )}
          {(source.coverage_description || source.coverage) && (
            <div className="flex items-center justify-between text-sm">
              <span className="text-bne-muted">Coverage</span>
              <span className="font-medium text-bne-ink">{source.coverage_description || source.coverage}</span>
            </div>
          )}
        </div>
      </CardContent>

      <CardFooter>
        <Button
          variant="primary"
          size="sm"
          onClick={() => onSync?.(source)}
          loading={Boolean(isSyncing || source.status === 'syncing')}
        >
          Sync Now
        </Button>
        <Button
          variant="outline"
          size="sm"
          onClick={() => onProbe?.(source)}
          loading={probePending}
        >
          Test connection
        </Button>
        <Button variant="outline" size="sm" onClick={() => onConfigure?.(source)}>
          Configure
        </Button>
        <Button variant="ghost" size="sm" onClick={() => onView?.(source)}>
          View Data
        </Button>
      </CardFooter>
    </Card>
  )
}

export default function DataSources() {
  const { data: sources, isLoading, error, refetch } = useDataSources()
  const { data: disclosure } = useDataDisclosure()
  const syncMutation = useSyncDataSource()
  const createMutation = useCreateDataSource()
  const updateMutation = useUpdateDataSource()
  const { data: healthPayload } = useDataSourceHealth()
  const probeMutation = useProbeDataSource()
  const [probeResults, setProbeResults] = useState<Record<string, ProbeResult | null>>({})

  // The health payload is the scheduler's view of each feed: cadence, last
  // outcome, next due date and the backoff factor while a feed fails.
  const healthById = useMemo(() => {
    const map = new Map<string, DataSourceHealthRow>()
    ;(healthPayload?.sources || []).forEach((row) => map.set(String(row.id), row))
    return map
  }, [healthPayload])

  const handleProbe = (source: DataSource) => {
    const id: EntityId | null | undefined = source.id || source.source_id
    probeMutation.mutate(id, {
      onSuccess: (result) => setProbeResults((prev) => ({ ...prev, [sourceKey(source)]: result })),
      onError: (probeError) =>
        setProbeResults((prev) => ({
          ...prev,
          [sourceKey(source)]: { success: false, message: probeError?.message || 'probe failed' }
        }))
    })
  }

  const handleSchedule = (source: DataSource, minutes: number | null) => {
    updateMutation.mutate({
      sourceId: source.id || source.source_id,
      sync_interval_minutes: minutes
    })
  }
  const [isFormOpen, setIsFormOpen] = useState(false)
  const [formMode, setFormMode] = useState<'create' | 'edit'>('create')
  const [formSource, setFormSource] = useState<DataSource | null>(null)
  const [detailsSource, setDetailsSource] = useState<DataSource | null>(null)

  // Plugin options come from the backend disclosure (the runtime registry),
  // not a hand-maintained frontend list: a feed the API cannot resolve must
  // not be selectable, and a feed it can must not be missing.
  const pluginOptions = useMemo(() => {
    const seen = new Set<string>()
    const base: Array<{ value: string; label: string }> = []
    ;(disclosure?.sources || []).forEach((source) => {
      if (source.plugin_type && !seen.has(source.plugin_type)) {
        base.push({ value: source.plugin_type, label: source.name || source.plugin_type })
        seen.add(source.plugin_type)
      }
    })
    ;(sources || []).forEach((source) => {
      const value = source.plugin_type
      if (value && !seen.has(value)) {
        base.push({ value, label: value })
        seen.add(value)
      }
    })
    return base
  }, [disclosure, sources])

  const [selectedDatasets, setSelectedDatasets] = useState<SelectedDataset[]>([])
  const selectedDatasetIds = useMemo<EntityId[]>(() => selectedDatasets.map((dataset) => dataset.id), [selectedDatasets])
  const [isJobModalOpen, setIsJobModalOpen] = useState(false)

  // The most recent real fetch across sources; "Never" when nothing has run.
  // A hardcoded relative time here would be a fabricated observation.
  // (Defined above the early returns: hooks must run in the same order on
  // every render.)
  const lastSyncLabel = useMemo(() => {
    const stamps = (sources || [])
      .map((s) => s.last_successful_fetch || s.updated_at || s.last_updated)
      .filter((stamp): stamp is string => Boolean(stamp))
      .map((s) => new Date(s).getTime())
      .filter((t) => !Number.isNaN(t))
    if (stamps.length === 0) return 'Never'
    return new Date(Math.max(...stamps)).toLocaleString()
  }, [sources])

  const handleDatasetSelection = (datasets: SelectedDataset[] = []) => {
    if (!datasets || datasets.length === 0) {
      return
    }
    setSelectedDatasets((prev) => {
      const map = new Map<EntityId, SelectedDataset>(prev.map((dataset) => [dataset.id, dataset]))
      datasets.forEach((dataset) => {
        if (dataset && typeof dataset.id !== 'undefined' && dataset.id !== null) {
          map.set(dataset.id, dataset)
        }
      })
      return Array.from(map.values())
    })
  }

  const handleRemoveSelectedDataset = (datasetId: EntityId) => {
    setSelectedDatasets((prev) => prev.filter((dataset) => dataset.id !== datasetId))
  }

  const handleClearSelectedDatasets = () => {
    setSelectedDatasets([])
  }

  const openJobModalWithSelection = () => {
    if (selectedDatasets.length === 0) {
      return
    }
    setIsJobModalOpen(true)
  }

  const currentSyncingId = syncMutation.isPending ? syncMutation.variables?.sourceId : null

  const handleSync = (source: DataSource) => {
    if (!source) return
    const sourceId = source.id || source.source_id
    if (!sourceId) return
    syncMutation.mutate({ sourceId })
  }

  const handleAddSource = () => {
    setFormMode('create')
    setFormSource(null)
    setIsFormOpen(true)
  }

  const handleConfigure = (source: DataSource) => {
    setFormMode('edit')
    setFormSource(source)
    setIsFormOpen(true)
  }

  const handleView = (source: DataSource) => {
    setDetailsSource(source)
  }

  const handleFormSubmit = async (payload: DataSourceFormPayload) => {
    if (formMode === 'create') {
      await createMutation.mutateAsync(payload)
    } else if (formMode === 'edit' && formSource) {
      const sourceId = formSource.id || formSource.source_id
      // Flat, not nested under `data`: the PUT body is the mutation
      // variables minus `sourceId` (see useUpdateDataSource), and the
      // backend's DataSourceUpdate schema reads top-level keys. The nested
      // shape Pydantic dropped made "Save Changes" a 200-answering no-op.
      await updateMutation.mutateAsync({ sourceId, ...payload })
    }
  }

  if (isLoading) {
    return (
      <PageContainer title="Data Sources">
        <div className="flex items-center justify-center h-64">
          <LoadingSpinner size="lg" message="Loading data sources..." />
        </div>
      </PageContainer>
    )
  }

  if (error) {
    return (
      <PageContainer title="Data Sources">
        <ErrorMessage
          title="Failed to load data sources"
          error={error}
          onRetry={refetch}
        />
      </PageContainer>
    )
  }

  const activeSources = sources?.filter((s) => s.status === 'active') || []
  const inactiveSources = sources?.filter((s) => s.status !== 'active') || []

  const workflowSteps = [
    {
      number: 1,
      title: 'Locate data by region',
      description: 'Filter catalogues by region or country, then pin the datasets that match your scenario.'
    },
    {
      number: 2,
      title: 'Review data health',
      description: 'Open any source to review freshness, coverage, and quick metrics before adding it to a job.'
    },
    {
      number: 3,
      title: 'Launch collection job',
      description: 'Use “Create Data Job” to download the selected datasets and run automated quality checks.'
    },
    {
      number: 4,
      title: 'Train and simulate',
      description: 'Once data jobs finish, train a model and jump into what-if scenarios from the Results tab.'
    }
  ]

  return (
    <>
      <PageContainer
        title="Data Sources"
        actions={
          <Button variant="primary" onClick={handleAddSource}>
            <span className="flex items-center gap-2">
              <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M12 4v16m8-8H4" />
            </svg>
            Add Source
          </span>
        </Button>
      }
      >
      <div className="space-y-8">
        <Card>
          <CardHeader>
            <CardTitle>How to prepare data for Beacon</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
              {workflowSteps.map((step) => (
                <div key={step.number} className="rounded-md border border-bne-line bg-bne-paper/40 p-4">
                  <div className="flex items-center gap-3">
                    <span className="flex h-8 w-8 items-center justify-center rounded-full bg-bne-pine text-bne-chalk text-sm font-semibold">
                      {step.number}
                    </span>
                    <h4 className="text-sm font-semibold text-bne-ink">{step.title}</h4>
                  </div>
                  <p className="text-xs text-bne-muted mt-3 leading-relaxed">{step.description}</p>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>

        <Card className="bg-bne-pine text-bne-chalk">
          <CardContent>
            <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
              <div>
                <p className="text-sm opacity-90 mb-2">Total Sources</p>
                <p className="text-3xl font-semibold">{sources?.length || 0}</p>
              </div>
              <div>
                <p className="text-sm opacity-90 mb-2">Active</p>
                <p className="text-3xl font-semibold">{activeSources.length}</p>
              </div>
              <div>
                <p className="text-sm opacity-90 mb-2">Last Sync</p>
                <p className="text-lg font-medium">{lastSyncLabel}</p>
              </div>
            </div>
          </CardContent>
        </Card>

        {selectedDatasets.length > 0 && (
          <Card>
            <CardHeader>
              <CardTitle>Selected Datasets</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="flex flex-wrap gap-2">
                {selectedDatasets.map((dataset) => (
                  <span
                    key={String(dataset.id)}
                    className="inline-flex items-center gap-2 rounded-full border border-bne-pine bg-bne-pine/10 px-3 py-1 text-sm text-bne-ink"
                  >
                    <div>
                      <span className="font-mono text-xs text-bne-ink">{dataset.code}</span>
                      <span className="block text-[11px] text-bne-muted/80">{dataset.name}</span>
                    </div>
                    <button
                      type="button"
                      onClick={() => handleRemoveSelectedDataset(dataset.id)}
                      className="ml-1 inline-flex h-5 w-5 items-center justify-center rounded-full bg-bne-pine text-bne-chalk text-xs hover:bg-bne-pine-600"
                      aria-label={`Remove ${dataset.code}`}
                    >
                      ×
                    </button>
                  </span>
                ))}
              </div>
              <p className="text-xs text-bne-muted mt-3">
                These datasets will be pre-filled when you create a new data collection job.
              </p>
            </CardContent>
            <CardFooter className="flex flex-wrap items-center gap-2">
              <Button variant="primary" onClick={openJobModalWithSelection}>
                Create Data Job
              </Button>
              <Button variant="ghost" onClick={handleClearSelectedDatasets}>
                Clear All
              </Button>
            </CardFooter>
          </Card>
        )}

        {activeSources.length > 0 && (
          <div>
            <h3 className="text-lg font-semibold text-bne-ink mb-4">Active Sources</h3>
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
              {activeSources.map((source, index) => (
                <DataSourceCard
                  key={sourceKey(source) || source.name || index}
                  source={source}
                  onSync={handleSync}
                  onConfigure={handleConfigure}
                  onView={handleView}
                  isSyncing={currentSyncingId === (source.id || source.source_id)}
                  health={healthById.get(sourceKey(source)) ?? null}
                  onProbe={handleProbe}
                  onSchedule={handleSchedule}
                  probePending={
                    probeMutation.isPending &&
                    probeMutation.variables === (source.id || source.source_id)
                  }
                  probeResult={probeResults[sourceKey(source)]}
                />
              ))}
            </div>
          </div>
        )}

        {inactiveSources.length > 0 && (
          <div>
            <h3 className="text-lg font-semibold text-bne-ink mb-4">Inactive Sources</h3>
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
              {inactiveSources.map((source, index) => (
                <DataSourceCard
                  key={sourceKey(source) || source.name || index}
                  source={source}
                  onSync={handleSync}
                  onConfigure={handleConfigure}
                  onView={handleView}
                  isSyncing={currentSyncingId === (source.id || source.source_id)}
                  health={healthById.get(sourceKey(source)) ?? null}
                  onProbe={handleProbe}
                  onSchedule={handleSchedule}
                  probePending={
                    probeMutation.isPending &&
                    probeMutation.variables === (source.id || source.source_id)
                  }
                  probeResult={probeResults[sourceKey(source)]}
                />
              ))}
            </div>
          </div>
        )}

        {sources?.length === 0 && (
          <Card className="border-2 border-dashed border-bne-line bg-bne-paper/50">
            <div className="text-center py-12">
              <svg
                className="w-16 h-16 mx-auto text-bne-muted/50 mb-4"
                fill="none"
                viewBox="0 0 24 24"
                stroke="currentColor"
                strokeWidth={2}
              >
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  d="M4 7v10c0 2.21 3.582 4 8 4s8-1.79 8-4V7M4 7c0 2.21 3.582 4 8 4s8-1.79 8-4M4 7c0-2.21 3.582-4 8-4s8 1.79 8 4m0 5c0 2.21-3.582 4-8 4s-8-1.79-8-4"
                />
              </svg>
              <h3 className="text-lg font-semibold text-bne-ink mb-2">No data sources configured</h3>
              <p className="text-sm text-bne-muted mb-4">
                Add your first data source to start collecting banking data
              </p>
              <Button variant="primary" onClick={handleAddSource}>
                Add Data Source
              </Button>
            </div>
          </Card>
        )}

        <Card>
          <CardHeader>
            <CardTitle>Provenance &amp; disclosure</CardTitle>
          </CardHeader>
          <CardContent>
            <p className="text-sm text-bne-muted mb-4">
              Where every input comes from, and what the platform infers rather than
              observes. Publisher, provenance class and coverage are curated on the
              backend; key requirements and configured counts describe this
              deployment, refreshed from the registry and database at request time.
            </p>
            {disclosure?.policy?.synthetic_data && (
              <div className="mb-4 rounded-md border border-bne-line bg-bne-paper-dim px-4 py-3">
                <p className="text-xs uppercase tracking-wide text-bne-muted mb-1">Data policy</p>
                <p className="text-sm text-bne-ink">{disclosure.policy.synthetic_data}</p>
              </div>
            )}
            {(disclosure?.sources?.length ?? 0) > 0 ? (
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-bne-line">
                      <th className="text-left py-2 pr-4 font-semibold text-bne-ink">Source</th>
                      <th className="text-left py-2 pr-4 font-semibold text-bne-ink">Publisher</th>
                      <th className="text-left py-2 pr-4 font-semibold text-bne-ink">Class</th>
                      <th className="text-left py-2 pr-4 font-semibold text-bne-ink">Provides</th>
                      <th className="text-left py-2 pr-4 font-semibold text-bne-ink">Access</th>
                      <th className="text-left py-2 font-semibold text-bne-ink">Configured</th>
                    </tr>
                  </thead>
                  <tbody>
                    {(disclosure?.sources ?? []).map((source) => {
                      const meta = PROVENANCE_CLASS_META[source.provenance_class] ||
                        { label: source.provenance_class, variant: 'default' as BadgeVariant }
                      return (
                        <tr key={source.plugin_type} className="border-b border-bne-line/60 align-top">
                          <td className="py-3 pr-4">
                            <span className="font-medium text-bne-ink">{source.name}</span>
                            <span className="block font-mono text-[11px] text-bne-muted">{source.plugin_type}</span>
                          </td>
                          <td className="py-3 pr-4 text-bne-muted">{source.publisher || '—'}</td>
                          <td className="py-3 pr-4">
                            <Badge variant={meta.variant} size="sm">{meta.label}</Badge>
                          </td>
                          <td className="py-3 pr-4 text-bne-muted max-w-md">
                            {source.provides || '—'}
                            {source.notes && (
                              <span className="block text-[11px] text-bne-faint mt-1">{source.notes}</span>
                            )}
                          </td>
                          <td className="py-3 pr-4">
                            {source.access?.key_required ? (
                              <Badge variant="warning" size="sm">Key required</Badge>
                            ) : (
                              <Badge variant="success" size="sm">Keyless</Badge>
                            )}
                          </td>
                          <td className="py-3">
                            <span className="font-mono text-bne-ink">
                              {source.deployment?.configured_sources ?? 0}
                            </span>
                            <span className="block text-[11px] text-bne-muted">
                              {source.deployment?.catalogue_items ?? 0} catalogue items
                            </span>
                          </td>
                        </tr>
                      )
                    })}
                  </tbody>
                </table>
              </div>
            ) : (
              <p className="text-sm text-bne-muted">Provenance disclosure is unavailable.</p>
            )}

            {(disclosure?.inferred_inputs?.length ?? 0) > 0 && (
              <div className="mt-6">
                <h4 className="text-sm font-semibold text-bne-ink mb-2">Inferred inputs</h4>
                <p className="text-xs text-bne-muted mb-3">
                  Quantities the platform estimates from real inputs instead of observing.
                  Each is labelled at every surface it appears on and excluded from the
                  observed-data stores.
                </p>
                {(disclosure?.inferred_inputs ?? []).map((input) => (
                  <div
                    key={input.name}
                    className="rounded-md border border-bne-ochre/30 bg-bne-ochre-50/40 px-4 py-3 mb-2"
                  >
                    <div className="flex flex-wrap items-center gap-2 mb-1">
                      <span className="font-mono text-xs text-bne-ink">{input.name}</span>
                      <Badge variant="warning" size="sm">Estimated</Badge>
                      <span className="text-[11px] text-bne-muted">via {input.produced_by}</span>
                    </div>
                    <p className="text-xs text-bne-muted">{input.method}</p>
                    <p className="text-xs text-bne-ink mt-1">{input.caveat}</p>
                  </div>
                ))}
              </div>
            )}

            {(disclosure?.orphaned_configurations?.length ?? 0) > 0 && (
              <div className="mt-4 rounded-md border border-bne-clay/30 bg-bne-clay-50/40 px-4 py-3">
                <p className="text-sm font-medium text-bne-ink mb-1">Configurations that cannot fetch</p>
                {(disclosure?.orphaned_configurations ?? []).map((orphan) => (
                  <p key={orphan.plugin_type} className="text-xs text-bne-muted font-mono">
                    {orphan.plugin_type}: {orphan.problem}
                  </p>
                ))}
              </div>
            )}
          </CardContent>
        </Card>
      </div>
      </PageContainer>
      <DataSourceFormModal
        isOpen={isFormOpen}
        mode={formMode}
        initialSource={formSource}
        pluginOptions={pluginOptions}
        onClose={() => setIsFormOpen(false)}
        onSubmit={handleFormSubmit}
      />
      <DataSourceDetailsModal
        isOpen={!!detailsSource}
        source={detailsSource}
        onClose={() => setDetailsSource(null)}
        preselectedDatasetIds={selectedDatasetIds}
        onApplySelection={handleDatasetSelection}
      />
      <JobCreationModal
        isOpen={isJobModalOpen}
        onClose={() => setIsJobModalOpen(false)}
        initialDatasets={selectedDatasets}
      />
    </>
  )
}

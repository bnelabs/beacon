import PageContainer from '../components/ui/PageContainer'
import Card, { CardHeader, CardTitle, CardContent, CardFooter } from '../components/ui/Card'
import Button from '../components/ui/Button'
import Badge from '../components/ui/Badge'
import LoadingSpinner from '../components/ui/LoadingSpinner'
import ErrorMessage from '../components/ui/ErrorMessage'
import {
  useCreateDataSource,
  useDataSources,
  useSyncDataSource,
  useUpdateDataSource
} from '../hooks/useApi'
import { useMemo, useState } from 'react'
import DataSourceFormModal from '../components/data-sources/DataSourceFormModal'
import DataSourceDetailsModal from '../components/data-sources/DataSourceDetailsModal'
import JobCreationModal from '../components/jobs/JobCreationModal'

const AVAILABLE_PLUGINS = [
  { value: 'fdic', label: 'FDIC', description: 'Federal Deposit Insurance Corporation', icon: '🏦', enabled: true },
  { value: 'ecb_banking', label: 'ECB Banking', description: 'European Central Bank Data', icon: '🇪🇺', enabled: true },
  { value: 'fmp', label: 'FMP', description: 'Financial Modeling Prep', icon: '📊', enabled: true },
  { value: 'yfinance', label: 'Yahoo Finance', description: 'Market data and financials', icon: '📈', enabled: false },
  { value: 'world_bank', label: 'World Bank', description: 'Global economic indicators', icon: '🌍', enabled: false },
  { value: 'imf', label: 'IMF', description: 'International Monetary Fund', icon: '💰', enabled: false },
  { value: 'fred', label: 'FRED', description: 'Federal Reserve Economic Data', icon: '🏛️', enabled: true },
  { value: 'bis', label: 'BIS', description: 'Bank for International Settlements', icon: '🌐', enabled: true },
  { value: 'sec_edgar', label: 'SEC EDGAR', description: 'SEC Company Filings', icon: '📄', enabled: true }
]

function DataSourceCard({ source, onSync, onConfigure, onView, isSyncing = false }) {
  const statusVariants = {
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
              <Badge variant={statusVariants[source.status] || 'default'} size="sm">
                {source.status || 'active'}
              </Badge>
            </div>
            <p className="text-sm text-bne-steel">{source.description}</p>
          </div>
        </div>
      </CardHeader>

      <CardContent>
        <div className="space-y-3">
          <div className="flex items-center justify-between text-sm">
            <span className="text-bne-steel">Source Type</span>
            <span className="font-medium text-bne-ink uppercase">
              {source.plugin_name || source.plugin_type || source.type}
            </span>
          </div>
          <div className="flex items-center justify-between text-sm">
            <span className="text-bne-steel">Last Updated</span>
            <span className="font-medium text-bne-ink">
              {lastUpdated ? new Date(lastUpdated).toLocaleDateString() : 'Never'}
            </span>
          </div>
          <div className="flex items-center justify-between text-sm">
            <span className="text-bne-steel">Records</span>
            <span className="font-medium text-bne-ink">{source.record_count?.toLocaleString() || '-'}</span>
          </div>
          {source.api_endpoint && (
            <div className="flex items-center justify-between text-sm">
              <span className="text-bne-steel">Endpoint</span>
              <span className="font-mono text-xs text-bne-ink truncate max-w-[200px]">
                {source.api_endpoint}
              </span>
            </div>
          )}
          {(source.coverage_description || source.coverage) && (
            <div className="flex items-center justify-between text-sm">
              <span className="text-bne-steel">Coverage</span>
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
  const syncMutation = useSyncDataSource()
  const createMutation = useCreateDataSource()
  const updateMutation = useUpdateDataSource()
  const [isFormOpen, setIsFormOpen] = useState(false)
  const [formMode, setFormMode] = useState('create')
  const [formSource, setFormSource] = useState(null)
  const [detailsSource, setDetailsSource] = useState(null)

  const pluginOptions = useMemo(() => {
    const seen = new Set()
    const base = []
    AVAILABLE_PLUGINS.forEach((plugin) => {
      if (!seen.has(plugin.value)) {
        base.push({ value: plugin.value, label: plugin.label })
        seen.add(plugin.value)
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
  }, [sources])

  const [selectedDatasets, setSelectedDatasets] = useState([])
  const selectedDatasetIds = useMemo(() => selectedDatasets.map((dataset) => dataset.id), [selectedDatasets])
  const [isJobModalOpen, setIsJobModalOpen] = useState(false)

  const handleDatasetSelection = (datasets = []) => {
    if (!datasets || datasets.length === 0) {
      return
    }
    setSelectedDatasets((prev) => {
      const map = new Map(prev.map((dataset) => [dataset.id, dataset]))
      datasets.forEach((dataset) => {
        if (dataset && typeof dataset.id !== 'undefined' && dataset.id !== null) {
          map.set(dataset.id, dataset)
        }
      })
      return Array.from(map.values())
    })
  }

  const handleRemoveSelectedDataset = (datasetId) => {
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

  const handleSync = (source) => {
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

  const handleConfigure = (source) => {
    setFormMode('edit')
    setFormSource(source)
    setIsFormOpen(true)
  }

  const handleView = (source) => {
    setDetailsSource(source)
  }

  const handleFormSubmit = async (payload) => {
    if (formMode === 'create') {
      await createMutation.mutateAsync(payload)
    } else if (formMode === 'edit' && formSource) {
      const sourceId = formSource.id || formSource.source_id
      await updateMutation.mutateAsync({ sourceId, data: payload })
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

  const activeSources = sources?.filter(s => s.status === 'active') || []
  const inactiveSources = sources?.filter(s => s.status !== 'active') || []

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
                <div key={step.number} className="rounded-xl border border-bne-frost bg-bne-ice/40 p-4">
                  <div className="flex items-center gap-3">
                    <span className="flex h-8 w-8 items-center justify-center rounded-full bg-bne-azure text-white text-sm font-semibold">
                      {step.number}
                    </span>
                    <h4 className="text-sm font-semibold text-bne-ink">{step.title}</h4>
                  </div>
                  <p className="text-xs text-bne-steel mt-3 leading-relaxed">{step.description}</p>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>

        <Card className="bg-gradient-to-br from-bne-azure to-bne-indigo text-white">
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
                <p className="text-lg font-medium">2 hours ago</p>
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
                    key={dataset.id}
                    className="inline-flex items-center gap-2 rounded-full border border-bne-azure bg-bne-azure/10 px-3 py-1 text-sm text-bne-ink"
                  >
                    <div>
                      <span className="font-mono text-xs text-bne-ink">{dataset.code}</span>
                      <span className="block text-[11px] text-bne-steel/80">{dataset.name}</span>
                    </div>
                    <button
                      type="button"
                      onClick={() => handleRemoveSelectedDataset(dataset.id)}
                      className="ml-1 inline-flex h-5 w-5 items-center justify-center rounded-full bg-bne-azure text-white text-xs hover:bg-bne-azure-600"
                      aria-label={`Remove ${dataset.code}`}
                    >
                      ×
                    </button>
                  </span>
                ))}
              </div>
              <p className="text-xs text-bne-steel mt-3">
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
              {activeSources.map((source) => (
                <DataSourceCard
                  key={source.id || source.source_id || source.name}
                  source={source}
                  onSync={handleSync}
                  onConfigure={handleConfigure}
                  onView={handleView}
                  isSyncing={currentSyncingId === (source.id || source.source_id)}
                />
              ))}
            </div>
          </div>
        )}

        {inactiveSources.length > 0 && (
          <div>
            <h3 className="text-lg font-semibold text-bne-ink mb-4">Inactive Sources</h3>
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
              {inactiveSources.map((source) => (
                <DataSourceCard
                  key={source.id || source.source_id || source.name}
                  source={source}
                  onSync={handleSync}
                  onConfigure={handleConfigure}
                  onView={handleView}
                  isSyncing={currentSyncingId === (source.id || source.source_id)}
                />
              ))}
            </div>
          </div>
        )}

        {sources?.length === 0 && (
          <Card className="border-2 border-dashed border-bne-frost bg-bne-ice/50">
            <div className="text-center py-12">
              <svg
                className="w-16 h-16 mx-auto text-bne-steel/50 mb-4"
                fill="none"
                viewBox="0 0 24 24"
                stroke="currentColor"
              >
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  strokeWidth={2}
                  d="M4 7v10c0 2.21 3.582 4 8 4s8-1.79 8-4V7M4 7c0 2.21 3.582 4 8 4s8-1.79 8-4M4 7c0-2.21 3.582-4 8-4s8 1.79 8 4m0 5c0 2.21-3.582 4-8 4s-8-1.79-8-4"
                />
              </svg>
              <h3 className="text-lg font-semibold text-bne-ink mb-2">No data sources configured</h3>
              <p className="text-sm text-bne-steel mb-4">
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
            <CardTitle>Available Plugins</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
              {AVAILABLE_PLUGINS.map((plugin) => (
                <div
                  key={plugin.value}
                  className={`p-4 rounded-lg border-2 ${
                    plugin.enabled
                      ? 'border-bne-azure/20 bg-bne-azure/5'
                      : 'border-bne-frost bg-white'
                  }`}
                >
                  <div className="flex items-start gap-3">
                    <span className="text-2xl">{plugin.icon}</span>
                    <div className="flex-1">
                      <div className="flex items-center gap-2 mb-1">
                        <h4 className="font-medium text-bne-ink">{plugin.label}</h4>
                        {plugin.enabled && (
                          <Badge variant="success" size="sm">Enabled</Badge>
                        )}
                      </div>
                      <p className="text-xs text-bne-steel">{plugin.description}</p>
                    </div>
                  </div>
                </div>
              ))}
            </div>
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

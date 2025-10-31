import { useEffect, useMemo, useState } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'
import { motion, AnimatePresence } from 'framer-motion'
import {
  fetchCatalogue,
  fetchDatasources,
  createJob,
  fetchJob,
  fetchBriefReport,
  fetchDetailedReport,
  fetchTrainingDefaults,
  API_BASE,
} from '../api/dataExplorer.js'
import { useUIStore } from '../state/uiStore.js'
import { RegionBadgeList } from './RegionBadgeList.jsx'
import { RegionDetails } from './RegionDetails.jsx'
import { ModelLibrary } from './ModelLibrary.jsx'
import { PredictionPanel } from './PredictionPanel.jsx'
import { BacktestPanel } from './BacktestPanel.jsx'

function PanelHeader({ title, subtitle, onBack }) {
  return (
    <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
      <div className="text-center sm:text-left">
        <p className="text-xs font-semibold uppercase tracking-[0.32em] text-bne-azure">{subtitle}</p>
        <h2 className="mt-2 text-xl font-semibold text-bne-ink">{title}</h2>
      </div>
      {onBack ? (
        <button
          type="button"
          onClick={onBack}
          className="rounded-full border border-bne-silver/60 px-4 py-1.5 text-xs font-medium text-bne-steel transition hover:border-bne-azure/60 hover:text-bne-azure"
        >
          Back
        </button>
      ) : null}
    </div>
  )
}

function DataSourceCard({ source, selected, onToggle }) {
  const coverageRange = useMemo(() => {
    if (!source.coverage.start && !source.coverage.end) {
      return 'Coverage window: not available'
    }

    const start = source.coverage.start ? new Date(source.coverage.start).toLocaleDateString() : '?'
    const end = source.coverage.end ? new Date(source.coverage.end).toLocaleDateString() : 'current'
    return `Coverage window: ${start} – ${end}`
  }, [source.coverage])

  return (
    <motion.button
      type="button"
      layout
      onClick={onToggle}
      className={`w-full rounded-2xl border px-5 py-4 text-left transition ${
        selected
          ? 'border-bne-azure/70 bg-bne-azure/10 shadow-bne-panel'
          : 'border-bne-silver/60 bg-white/60 hover:border-bne-azure/50'
      }`}
    >
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div className="text-center sm:text-left">
          <h3 className="text-sm font-semibold text-bne-ink">{source.name}</h3>
          <p className="text-xs uppercase tracking-[0.18em] text-bne-steel/70">{source.plugin_type}</p>
        </div>
        <div
          className={`h-2 w-2 rounded-full ${source.status === 'error' ? 'bg-red-500' : 'bg-bne-emerald'}`}
          title={source.status === 'error' ? 'Source reporting errors' : 'Source healthy'}
        />
      </div>
      <p className="mt-3 text-xs text-bne-steel/80">{coverageRange}</p>
      <div className="mt-3 flex flex-wrap items-center gap-2 text-[11px] uppercase text-bne-steel/70">
        <span className="rounded-full bg-bne-ice/90 px-2 py-1">
          {source.coverage.asset_count} assets
        </span>
        {source.regions.map((region) => (
          <span key={region} className="rounded-full bg-bne-ice/90 px-2 py-1">
            {region.replace('_', ' ').toUpperCase()}
          </span>
        ))}
      </div>
    </motion.button>
  )
}

function CatalogueCard({ asset, selected, onToggle }) {
  return (
    <motion.button
      type="button"
      layout
      onClick={onToggle}
      className={`w-full rounded-2xl border px-5 py-4 text-left transition ${
        selected
          ? 'border-bne-azure/70 bg-bne-azure/10 shadow-bne-panel'
          : 'border-bne-silver/60 bg-white/70 hover:border-bne-azure/50'
      }`}
    >
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div className="text-center sm:text-left">
          <p className="text-sm font-semibold text-bne-ink">{asset.name}</p>
          <p className="text-xs uppercase tracking-[0.2em] text-bne-steel/60">{asset.code}</p>
        </div>
        <div className="text-xs text-bne-steel/70 sm:text-right">
          <p>{asset.category.replace('_', ' ')}</p>
          <p>{asset.region.replace('_', ' ')}</p>
        </div>
      </div>
      {asset.description ? (
        <p className="mt-2 text-xs leading-relaxed text-bne-steel/80">{asset.description}</p>
      ) : null}
      <div className="mt-3 flex flex-wrap items-center gap-2 text-[11px] uppercase text-bne-steel/70">
        {asset.risk_types.map((risk) => (
          <span key={risk} className="rounded-full bg-bne-ice/90 px-2 py-1">
            {risk.replace('_', ' ')}
          </span>
        ))}
        {asset.frequency ? (
          <span className="rounded-full bg-bne-ice/90 px-2 py-1">{asset.frequency}</span>
        ) : null}
      </div>
    </motion.button>
  )
}

function DatasourceSelection({ selectedRegions }) {
  const selectedSourceIds = useUIStore((state) => state.selectedSourceIds)
  const toggleSource = useUIStore((state) => state.toggleSource)
  const setPanelStage = useUIStore((state) => state.setPanelStage)

  const query = useQuery({
    queryKey: ['v2-datasources', selectedRegions],
    queryFn: () => fetchDatasources({ regions: selectedRegions }),
    enabled: selectedRegions.length > 0,
    staleTime: 60_000,
  })

  if (query.isLoading) {
    return (
      <div className="flex h-48 items-center justify-center text-sm text-bne-steel/70">
        Loading data sources…
      </div>
    )
  }

  if (query.isError) {
    return (
      <div className="rounded-3xl border border-red-200 bg-red-50/90 p-4 text-sm text-red-700">
        {query.error?.message ?? 'Unable to load data sources.'}
        {query.error?.technical ? (
          <p className="mt-2 text-xs text-red-500/80">Details: {query.error.technical}</p>
        ) : null}
      </div>
    )
  }

  const sources = query.data?.sources ?? []

  return (
    <div className="space-y-5">
      <PanelHeader title="Select Data Sources" subtitle="Data Sources" />
      <p className="text-sm text-bne-steel/80">
        Choose the institutional feeds you want to activate for the selected regions. You can continue to
        the data catalogue once at least one source is selected.
      </p>
      <div className="space-y-3">
        <AnimatePresence initial={false}>
          {sources.map((source) => (
            <DataSourceCard
              key={source.id}
              source={source}
              selected={selectedSourceIds.includes(source.id)}
              onToggle={() => toggleSource(source.id)}
            />
          ))}
        </AnimatePresence>
      </div>
      <div className="rounded-2xl border border-dashed border-bne-silver/60 bg-white/50 p-4 text-sm text-bne-steel/80">
        <p className="font-medium text-bne-steel">Connect to private feeds</p>
        <p className="mt-1 text-xs leading-relaxed">
          Need to ingest a secured bank API? Use the connector console to add encrypted credentials and
          register bespoke data sources.
        </p>
      </div>
      <button
        type="button"
        onClick={() => setPanelStage('catalog')}
        disabled={selectedSourceIds.length === 0}
        className="w-full rounded-full bg-bne-azure px-5 py-3 text-sm font-semibold text-white transition hover:bg-bne-azure/90 disabled:cursor-not-allowed disabled:bg-bne-silver/60"
      >
        Continue to Data Catalog
      </button>
    </div>
  )
}

function CatalogueList({ selectedSourceIds }) {
  const setPanelStage = useUIStore((state) => state.setPanelStage)
  const selectedAssetIds = useUIStore((state) => state.selectedAssetIds)
  const toggleAsset = useUIStore((state) => state.toggleAsset)
  const [search, setSearch] = useState('')

  const query = useQuery({
    queryKey: ['v2-catalogue', selectedSourceIds, search],
    queryFn: () => fetchCatalogue({ sourceIds: selectedSourceIds, search }),
    enabled: selectedSourceIds.length > 0,
    staleTime: 30_000,
  })

  const assets = query.data?.assets ?? []

  return (
    <div className="space-y-5">
      <PanelHeader
        title="Data Catalogue"
        subtitle="Assets"
        onBack={() => setPanelStage('sources')}
      />

      <div className="rounded-2xl bg-white/80 p-3 shadow-inner">
        <input
          type="search"
          value={search}
          onChange={(event) => setSearch(event.target.value)}
          placeholder="Search tickers, indices, liquidity metrics…"
          className="w-full rounded-full border border-bne-silver/60 bg-white/80 px-4 py-2 text-sm text-bne-steel focus:outline-none focus:ring-2 focus:ring-bne-azure/40"
        />
      </div>

      {selectedSourceIds.length === 0 ? (
        <div className="rounded-2xl border border-bne-silver/60 bg-white/70 p-4 text-sm text-bne-steel/80">
          Select at least one data source to view the linked catalogue assets.
        </div>
      ) : query.isLoading ? (
        <div className="flex h-48 items-center justify-center text-sm text-bne-steel/70">
          Loading catalogue assets…
        </div>
      ) : query.isError ? (
        <div className="rounded-3xl border border-red-200 bg-red-50/90 p-4 text-sm text-red-700">
          {query.error?.message ?? 'Unable to load data catalogue.'}
          {query.error?.technical ? (
            <p className="mt-2 text-xs text-red-500/80">Details: {query.error.technical}</p>
          ) : null}
        </div>
      ) : assets.length === 0 ? (
        <div className="rounded-3xl border border-bne-silver/60 bg-white/70 p-4 text-sm text-bne-steel/80">
          No catalogue assets match your current filters.
        </div>
      ) : (
        <div className="space-y-3">
          <AnimatePresence initial={false}>
            {assets.map((asset) => (
              <CatalogueCard
                key={asset.id}
                asset={asset}
                selected={selectedAssetIds.includes(asset.id)}
                onToggle={() => toggleAsset(asset.id)}
              />
            ))}
          </AnimatePresence>
        </div>
      )}

      <div className="flex items-center justify-between rounded-2xl bg-white/70 px-4 py-3 text-xs text-bne-steel/80">
        <span>{selectedAssetIds.length} assets selected</span>
        <button
          type="button"
          onClick={() => setPanelStage('download')}
          disabled={selectedAssetIds.length === 0}
          className="rounded-full bg-bne-azure px-4 py-2 text-xs font-semibold text-white transition hover:bg-bne-azure/90 disabled:cursor-not-allowed disabled:bg-bne-silver/60"
        >
          Continue to Download
        </button>
      </div>
    </div>
  )
}

function DownloadPanel({ selectedRegions, selectedCountries, selectedSourceIds, selectedAssetIds }) {
  const setPanelStage = useUIStore((state) => state.setPanelStage)
  const resetAssets = useUIStore((state) => state.resetAssets)
  const setDataJobId = useUIStore((state) => state.setDataJobId)
  const setConfirmedScope = useUIStore((state) => state.setConfirmedScope)
  const confirmedRegions = useUIStore((state) => state.confirmedRegions)
  const confirmedCountries = useUIStore((state) => state.confirmedCountries)
  const [jobId, setJobId] = useState(null)

  const startJob = useMutation({
    mutationFn: (payload) => createJob(payload),
    onSuccess: (data) => {
      setJobId(data.id)
    },
  })

  const jobQuery = useQuery({
    queryKey: ['job-status', jobId],
    queryFn: () => fetchJob(jobId),
    enabled: Boolean(jobId),
    refetchInterval: (data) => {
      if (!data) return false
      const status = data.status
      return status && !['completed', 'failed'].includes(status) ? 3000 : false
    },
  })

  const jobData = jobQuery.data
  const jobStatus = jobData?.status
  const jobProgress = jobData?.progress ?? 0
  const jobStep = jobData?.current_step
  const jobError = jobData?.error_message || jobData?.user_friendly_error
  const jobCompleted = jobStatus === 'completed'
  const jobFailed = jobStatus === 'failed'

  const briefQuery = useQuery({
    queryKey: ['v2-brief-report', jobId],
    queryFn: () => fetchBriefReport(jobId),
    enabled: Boolean(jobId) && jobCompleted,
    staleTime: 0,
  })

  const detailedQuery = useQuery({
    queryKey: ['v2-detailed-report', jobId],
    queryFn: () => fetchDetailedReport(jobId),
    enabled: Boolean(jobId) && jobCompleted,
    staleTime: 0,
  })

  const brief = briefQuery.data
  const effectiveRegions = brief?.regions?.length ? brief.regions : confirmedRegions.length ? confirmedRegions : selectedRegions
  const effectiveCountries = brief?.countries?.length ? brief.countries : confirmedCountries.length ? confirmedCountries : selectedCountries
  const detailed = detailedQuery.data

  const handleStart = () => {
    const payload = {
      job_type: 'data_collection',
      parameters: {
        catalogue_items: selectedAssetIds,
        regions: selectedRegions,
        countries: selectedCountries,
        sources: selectedSourceIds,
      },
    }
    setConfirmedScope([], [])
    startJob.mutate(payload)
  }

  useEffect(() => {
    if (jobCompleted && jobId) {
      setDataJobId(jobId)
      if (brief?.regions || brief?.countries) {
        setConfirmedScope(brief?.regions, brief?.countries)
      }
    }
  }, [jobCompleted, jobId, brief?.regions, brief?.countries, setDataJobId, setConfirmedScope])

  return (
    <div className="space-y-5">
      <PanelHeader
        title="Data Download"
        subtitle="Pipeline"
        onBack={() => {
          setPanelStage('catalog')
          resetAssets()
        }}
      />

      <div className="rounded-2xl border border-bne-silver/60 bg-white/70 p-4 text-sm text-bne-steel/80">
        <p className="font-semibold text-bne-steel">Summary</p>
        <div className="mt-2 space-y-1 text-xs text-bne-steel/80">
          <p>
            {selectedAssetIds.length} assets across {selectedSourceIds.length} data sources will be collected for
            regions {effectiveRegions.join(', ')}.
          </p>
          {effectiveCountries.length > 0 ? (
            <p>
              Country focus applied: {effectiveCountries.join(', ')}.
            </p>
          ) : null}
        </div>
      </div>

      {jobId === null ? (
        <button
          type="button"
          onClick={handleStart}
          disabled={startJob.isLoading}
          className="w-full rounded-full bg-bne-azure px-5 py-3 text-sm font-semibold text-white transition hover:bg-bne-azure/90 disabled:cursor-not-allowed disabled:bg-bne-silver/60"
        >
          {startJob.isLoading ? 'Starting download…' : 'Start Download'}
        </button>
      ) : (
        <div className="rounded-3xl bg-white/70 p-5 shadow-bne-panel">
          <div className="flex items-center justify-between text-sm font-medium text-bne-ink">
            <span>Status: {jobStatus}</span>
            <span>{Math.round(jobProgress)}%</span>
          </div>
          <div className="mt-3 h-2 rounded-full bg-bne-ice">
            <div
              className="h-full rounded-full bg-bne-azure transition-all"
              style={{ width: `${Math.min(100, Math.round(jobProgress))}%` }}
            />
          </div>
          {jobStep ? (
            <p className="mt-2 text-xs text-bne-steel/70">{jobStep}</p>
          ) : null}
          {jobError ? (
            <p className="mt-3 text-xs text-red-600">{jobError}</p>
          ) : null}
        </div>
      )}

      {jobCompleted ? (
        <div className="space-y-4">
          <div className="rounded-3xl border border-bne-silver/60 bg-white/80 p-5 shadow-sm">
            <p className="text-sm font-semibold text-bne-ink">Download Summary</p>
            {brief ? (
              <div className="mt-3 grid grid-cols-2 gap-3 text-xs text-bne-steel/80">
                <div>
                  <p className="font-semibold text-bne-steel">Assets collected</p>
                  <p>{brief.downloaded}</p>
                </div>
                <div>
                  <p className="font-semibold text-bne-steel">Fit-for-purpose score</p>
                  <p>{brief.fit_for_purpose_score?.toFixed(2) ?? 'n/a'}</p>
                </div>
                <div>
                  <p className="font-semibold text-bne-steel">Completeness</p>
                  <p>{brief.quality_metrics.completeness?.toFixed(3) ?? 'n/a'}</p>
                </div>
                <div>
                  <p className="font-semibold text-bne-steel">Total observations</p>
                  <p>{brief.total_observations}</p>
                </div>
                <div>
                  <p className="font-semibold text-bne-steel">Regions processed</p>
                  <p>{brief.regions?.length ? brief.regions.join(', ') : 'All'}</p>
                </div>
                <div>
                  <p className="font-semibold text-bne-steel">Country focus</p>
                  <p>{brief.countries?.length ? brief.countries.join(', ') : 'All'}</p>
                </div>
              </div>
            ) : (
              <p className="mt-2 text-xs text-bne-steel/70">Loading summary…</p>
            )}
          </div>

          <div className="space-y-3">
            <p className="text-sm font-semibold text-bne-ink">Asset Diagnostics</p>
            {detailed?.assets?.map((asset) => (
              <div key={asset.source_code} className="rounded-2xl border border-bne-silver/60 bg-white/70 p-4 text-xs text-bne-steel/80">
                <div className="flex items-center justify-between">
                  <span className="font-semibold text-bne-ink">{asset.source_code}</span>
                  <span>{asset.records} rows</span>
                </div>
                <div className="mt-2 grid grid-cols-2 gap-2">
                  <p>Missing: {asset.missing_values}</p>
                  <p>Anomaly ratio: {asset.anomaly_ratio ? (asset.anomaly_ratio * 100).toFixed(2) + '%' : 'n/a'}</p>
                  <p>Mean: {asset.value_mean?.toFixed(4) ?? 'n/a'}</p>
                  <p>Std dev: {asset.value_std?.toFixed(4) ?? 'n/a'}</p>
                </div>
                <p className="mt-2 text-[11px] text-bne-steel/60">
                  Coverage {asset.coverage_start ? new Date(asset.coverage_start).toLocaleDateString() : '?'} –
                  {asset.coverage_end ? new Date(asset.coverage_end).toLocaleDateString() : 'current'}
                </p>
              </div>
            ))}
          </div>

          <button
            type="button"
            onClick={() => setPanelStage('training')}
            className="w-full rounded-full bg-bne-emerald px-5 py-3 text-sm font-semibold text-white transition hover:bg-bne-emerald/90"
          >
            Proceed to Training
          </button>
        </div>
      ) : null}

      {jobFailed ? (
        <div className="rounded-2xl border border-red-200 bg-red-50/90 p-4 text-sm text-red-700">
          The download job failed. Please review the configuration and try again.
        </div>
      ) : null}
    </div>
  )
}

function TrainingPanel({ dataJobId, selectedRegions, selectedSourceIds, selectedAssetIds }) {
  const setPanelStage = useUIStore((state) => state.setPanelStage)
  const trainingJobId = useUIStore((state) => state.trainingJobId)
  const setTrainingJobId = useUIStore((state) => state.setTrainingJobId)
  const resetWorkflow = useUIStore((state) => state.resetWorkflow)
  const setSelectedModelId = useUIStore((state) => state.setSelectedModelId)
  const confirmedRegions = useUIStore((state) => state.confirmedRegions)
  const confirmedCountries = useUIStore((state) => state.confirmedCountries)

  const defaultsQuery = useQuery({
    queryKey: ['training-defaults'],
    queryFn: fetchTrainingDefaults,
    staleTime: 60_000,
  })

  const [formValues, setFormValues] = useState(null)

  useEffect(() => {
    if (defaultsQuery.data?.defaults && !formValues) {
      setFormValues(defaultsQuery.data.defaults)
    }
  }, [defaultsQuery.data, formValues])

  const trainingMutation = useMutation({
    mutationFn: (payload) => createJob(payload),
    onSuccess: (data) => {
      setTrainingJobId(data.id)
    },
  })

  const trainingJobQuery = useQuery({
    queryKey: ['job-status', trainingJobId],
    queryFn: () => fetchJob(trainingJobId),
    enabled: Boolean(trainingJobId),
    refetchInterval: (data) => {
      if (!data) return false
      const status = data.status
      return status && !['completed', 'failed'].includes(status) ? 4000 : false
    },
  })

  const trainingJob = trainingJobQuery.data
  const trainingStatus = trainingJob?.status
  const trainingProgress = trainingJob?.progress ?? 0
  const trainingStep = trainingJob?.current_step
  const trainingError = trainingJob?.error_message || trainingJob?.user_friendly_error
  const trainingCompleted = trainingStatus === 'completed'
  const trainingFailed = trainingStatus === 'failed'

  const trainingResult = trainingJob?.result
  const [modelPrepNotified, setModelPrepNotified] = useState(false)

  useEffect(() => {
    setModelPrepNotified(false)
  }, [trainingJobId])

  useEffect(() => {
    if (trainingCompleted && trainingJobId && !modelPrepNotified) {
      setSelectedModelId(trainingJobId)
      setModelPrepNotified(true)
    }
  }, [trainingCompleted, trainingJobId, modelPrepNotified, setSelectedModelId])

  const handleChange = (key, value) => {
    setFormValues((prev) => ({ ...prev, [key]: value }))
  }

  const handleStartTraining = () => {
    if (!formValues || !dataJobId) return
    const payload = {
      job_type: 'training',
      parameters: {
        data_job_id: dataJobId,
        config: formValues,
      },
    }
    trainingMutation.mutate(payload)
  }

  if (!dataJobId) {
    return (
      <div className="space-y-5">
        <PanelHeader title="Training" subtitle="Pipeline" onBack={() => setPanelStage('download')} />
        <div className="rounded-2xl border border-bne-silver/60 bg-white/70 p-4 text-sm text-bne-steel/80">
          Complete a data download before launching training.
        </div>
      </div>
    )
  }

  const scopeRegions = confirmedRegions.length > 0 ? confirmedRegions : selectedRegions
  const scopeCountries = confirmedCountries.length > 0 ? confirmedCountries : []

  return (
    <div className="space-y-5">
      <PanelHeader title="Model Training" subtitle="Pipeline" onBack={() => setPanelStage('download')} />

      <div className="rounded-2xl border border-bne-silver/60 bg-white/70 p-4 text-xs text-bne-steel/80">
        <p className="text-sm font-semibold text-bne-ink">Scope</p>
        <p className="mt-2">
          Regions: {scopeRegions.join(', ')} | Sources: {selectedSourceIds.length} | Assets: {selectedAssetIds.length}
        </p>
        {scopeCountries.length > 0 ? (
          <p>
            Confirmed country focus: {scopeCountries.join(', ')}
          </p>
        ) : null}
      </div>

      {defaultsQuery.isLoading || !formValues ? (
        <div className="flex h-48 items-center justify-center text-sm text-bne-steel/70">
          Loading training defaults…
        </div>
      ) : (
        <div className="space-y-4 rounded-3xl bg-white/70 p-5 shadow-bne-panel">
          <p className="text-sm font-semibold text-bne-ink">Hyperparameters</p>
          <div className="grid grid-cols-2 gap-4 text-sm text-bne-steel/80">
            <label className="flex flex-col gap-1">
              <span>Sequence Length</span>
              <input
                type="number"
                value={formValues.sequence_length}
                min="30"
                max="180"
                onChange={(event) => handleChange('sequence_length', Number(event.target.value))}
                className="rounded-xl border border-bne-silver/60 bg-white/80 px-3 py-2 focus:outline-none focus:ring-2 focus:ring-bne-azure/40"
              />
            </label>
            <label className="flex flex-col gap-1">
              <span>Batch Size</span>
              <input
                type="number"
                value={formValues.batch_size}
                min="8"
                max="256"
                onChange={(event) => handleChange('batch_size', Number(event.target.value))}
                className="rounded-xl border border-bne-silver/60 bg-white/80 px-3 py-2 focus:outline-none focus:ring-2 focus:ring-bne-azure/40"
              />
            </label>
            <label className="flex flex-col gap-1">
              <span>Epochs</span>
              <input
                type="number"
                value={formValues.num_epochs}
                min="10"
                max="500"
                onChange={(event) => handleChange('num_epochs', Number(event.target.value))}
                className="rounded-xl border border-bne-silver/60 bg-white/80 px-3 py-2 focus:outline-none focus:ring-2 focus:ring-bne-azure/40"
              />
            </label>
            <label className="flex flex-col gap-1">
              <span>Learning Rate</span>
              <input
                type="number"
                step="0.0001"
                value={formValues.learning_rate}
                onChange={(event) => handleChange('learning_rate', Number(event.target.value))}
                className="rounded-xl border border-bne-silver/60 bg-white/80 px-3 py-2 focus:outline-none focus:ring-2 focus:ring-bne-emerald/40"
              />
            </label>
            <label className="flex flex-col gap-1">
              <span>Validation Split</span>
              <input
                type="number"
                step="0.05"
                min="0.1"
                max="0.4"
                value={formValues.validation_split}
                onChange={(event) => handleChange('validation_split', Number(event.target.value))}
                className="rounded-xl border border-bne-silver/60 bg-white/80 px-3 py-2 focus:outline-none focus:ring-2 focus:ring-bne-emerald/40"
              />
            </label>
            <label className="flex flex-col gap-1">
              <span>Early Stopping Patience</span>
              <input
                type="number"
                min="5"
                max="30"
                value={formValues.early_stopping_patience}
                onChange={(event) => handleChange('early_stopping_patience', Number(event.target.value))}
                className="rounded-xl border border-bne-silver/60 bg-white/80 px-3 py-2 focus:outline-none focus:ring-2 focus:ring-bne-emerald/40"
              />
            </label>
            <label className="flex flex-col gap-1">
              <span>Model</span>
              <select
                value={formValues.model}
                onChange={(event) => handleChange('model', event.target.value)}
                className="rounded-xl border border-bne-silver/60 bg-white/80 px-3 py-2 focus:outline-none focus:ring-2 focus:ring-bne-emerald/40"
              >
                <option value="temporal_attention">Temporal Attention</option>
                <option value="hgt">Heterogeneous Graph Transformer</option>
                <option value="ensemble">Ensemble</option>
              </select>
            </label>
            <label className="flex flex-col gap-1">
              <span>Optimizer</span>
              <select
                value={formValues.optimizer}
                onChange={(event) => handleChange('optimizer', event.target.value)}
                className="rounded-xl border border-bne-silver/60 bg-white/80 px-3 py-2 focus:outline-none focus:ring-2 focus:ring-bne-emerald/40"
              >
                <option value="adamw">AdamW</option>
                <option value="adam">Adam</option>
                <option value="sgd">SGD</option>
              </select>
            </label>
          </div>
        </div>
      )}

      {trainingJobId === null ? (
        <button
          type="button"
          onClick={handleStartTraining}
          disabled={trainingMutation.isLoading}
          className="w-full rounded-full bg-bne-emerald px-5 py-3 text-sm font-semibold text-white transition hover:bg-bne-emerald/90 disabled:cursor-not-allowed disabled:bg-bne-silver/60"
        >
          {trainingMutation.isLoading ? 'Launching training…' : 'Start Training'}
        </button>
      ) : (
        <div className="rounded-3xl bg-white/70 p-5 shadow-bne-panel">
          <div className="flex items-center justify-between text-sm font-medium text-bne-ink">
            <span>Status: {trainingStatus}</span>
            <span>{Math.round(trainingProgress)}%</span>
          </div>
          <div className="mt-3 h-2 rounded-full bg-bne-ice">
            <div
              className="h-full rounded-full bg-bne-emerald transition-all"
              style={{ width: `${Math.min(100, Math.round(trainingProgress))}%` }}
            />
          </div>
          {trainingStep ? (
            <p className="mt-2 text-xs text-bne-steel/70">{trainingStep}</p>
          ) : null}
          {trainingError ? (
            <p className="mt-3 text-xs text-red-600">{trainingError}</p>
          ) : null}
        </div>
      )}

      {trainingCompleted && trainingResult ? (
        <div className="space-y-4">
          <div className="rounded-3xl border border-bne-silver/60 bg-white/80 p-5 shadow-sm text-xs text-bne-steel/80">
            <p className="text-sm font-semibold text-bne-ink">Training Results</p>
            <div className="mt-3 grid grid-cols-2 gap-3">
              <p>Best epoch: {trainingResult.best_epoch ?? 'n/a'}</p>
              <p>Epochs trained: {trainingResult.epochs_trained ?? 'n/a'}</p>
              <p>Final train loss: {trainingResult.final_train_loss?.toFixed(4) ?? 'n/a'}</p>
              <p>Final val loss: {trainingResult.final_val_loss?.toFixed(4) ?? 'n/a'}</p>
              <p>Test MAE: {trainingResult.test_mae?.toFixed(4) ?? 'n/a'}</p>
              <p>Test RMSE: {trainingResult.test_rmse?.toFixed(4) ?? 'n/a'}</p>
              <p>Test R²: {trainingResult.test_r2?.toFixed(4) ?? 'n/a'}</p>
            </div>
          </div>

          <button
            type="button"
            onClick={() => {
              if (trainingJobId) {
                setSelectedModelId(trainingJobId)
              }
              setPanelStage('model-library')
            }}
            className="w-full rounded-full bg-bne-azure px-5 py-3 text-sm font-semibold text-white transition hover:bg-bne-azure/90"
          >
            Open Model Library
          </button>

          <div className="rounded-3xl border border-bne-silver/60 bg-white/80 p-5 shadow-sm text-xs text-bne-steel/80">
            <p className="text-sm font-semibold text-bne-ink">Downloads</p>
            <div className="mt-3 space-y-2">
              <a
                href={`${API_BASE}/api/v1/reports/download/${trainingJobId}?format=pdf`}
                className="inline-flex items-center gap-2 rounded-full border border-bne-azure/40 px-4 py-2 text-xs font-semibold text-bne-azure transition hover:border-bne-azure hover:text-bne-ink"
              >
                Download PDF Report
              </a>
              <a
                href={`${API_BASE}/api/v1/reports/download/${trainingJobId}?format=excel`}
                className="inline-flex items-center gap-2 rounded-full border border-bne-azure/40 px-4 py-2 text-xs font-semibold text-bne-azure transition hover:border-bne-azure hover:text-bne-ink"
              >
                Download Excel Report
              </a>
            </div>
          </div>

          <button
            type="button"
            onClick={() => {
              resetWorkflow()
            }}
            className="w-full rounded-full border border-bne-silver/60 px-5 py-3 text-sm font-semibold text-bne-steel transition hover:border-bne-emerald/60 hover:text-bne-emerald"
          >
            Reset Workflow
          </button>
        </div>
      ) : null}

      {trainingFailed ? (
        <div className="rounded-2xl border border-red-200 bg-red-50/90 p-4 text-sm text-red-700">
          Training job failed. Adjust hyperparameters and retry.
        </div>
      ) : null}
    </div>
  )
}

export function RegionDataPanel() {
  const selectedRegions = useUIStore((state) => state.selectedRegions)
  const selectedCountries = useUIStore((state) => state.selectedCountries)
  const resetWorkflow = useUIStore((state) => state.resetWorkflow)
  const panelStage = useUIStore((state) => state.panelStage)
  const selectedSourceIds = useUIStore((state) => state.selectedSourceIds)
  const selectedAssetIds = useUIStore((state) => state.selectedAssetIds)
  const dataJobId = useUIStore((state) => state.dataJobId)
  const selectedModelId = useUIStore((state) => state.selectedModelId)

  const regionKey = useMemo(() => selectedRegions.join(','), [selectedRegions])

  useEffect(() => {
    resetWorkflow()
  }, [resetWorkflow, regionKey])

  if (selectedRegions.length === 0) {
    return (
      <div className="flex h-full flex-col gap-6">
        <PanelHeader title="Region Intelligence Console" subtitle="Navigator" />
        <p className="text-sm text-bne-steel/80">
          Select a geographic region on the globe to discover connected data sources, catalogue entries, and
          pipeline readiness.
        </p>
      </div>
    )
  }

  const stageContent = (() => {
    switch (panelStage) {
      case 'sources':
        return <DatasourceSelection selectedRegions={selectedRegions} />
      case 'catalog':
        return <CatalogueList selectedSourceIds={selectedSourceIds} />
      case 'download':
        return (
          <DownloadPanel
            selectedRegions={selectedRegions}
            selectedCountries={selectedCountries}
            selectedSourceIds={selectedSourceIds}
            selectedAssetIds={selectedAssetIds}
          />
        )
      case 'training':
        return (
          <TrainingPanel
            dataJobId={dataJobId}
            selectedRegions={selectedRegions}
            selectedSourceIds={selectedSourceIds}
            selectedAssetIds={selectedAssetIds}
          />
        )
      case 'model-library':
        return <ModelLibrary />
      case 'prediction':
        return <PredictionPanel modelId={selectedModelId} />
      case 'backtest':
        return <BacktestPanel modelId={selectedModelId} />
      default:
        return null
    }
  })()

  return (
    <div className="space-y-5">
      <RegionBadgeList />
      <RegionDetails />
      <AnimatePresence mode="wait">
        {stageContent ? (
          <motion.div
            key={panelStage}
            initial={{ opacity: 0, x: 16 }}
            animate={{ opacity: 1, x: 0 }}
            exit={{ opacity: 0, x: -16 }}
            transition={{ duration: 0.25, ease: [0.25, 0.1, 0.25, 1] }}
          >
            {stageContent}
          </motion.div>
        ) : null}
      </AnimatePresence>
    </div>
  )
}

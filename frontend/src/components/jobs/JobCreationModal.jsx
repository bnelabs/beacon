import { useEffect, useMemo, useState, useCallback } from 'react'
import Modal from '../ui/Modal'
import Button from '../ui/Button'
import { useCatalogueItems, useCreateJob, useJobs } from '../../hooks/useApi'

const JOB_TYPES = [
  {
    value: 'data_collection',
    label: 'Data Collection',
    description: 'Download and prepare data from the configured catalogue.'
  },
  {
    value: 'training',
    label: 'Model Training',
    description: 'Train an AI model using a completed data collection job.'
  }
]

const MODEL_TYPE_DESCRIPTIONS = {
  temporal_attention: 'Balances short-term volatility with longer sequences. Good default when unsure.',
  hgt: 'Captures interactions between entities (e.g., banks, regions) using a graph transformer.',
  lstm: 'Classic recurrent network for smoother time series with fewer cross-dependencies.'
}

const REGION_OPTIONS = [
  { value: '', label: 'All Regions' },
  { value: 'global', label: 'Global' },
  { value: 'north_america', label: 'North America' },
  { value: 'europe', label: 'Europe' },
  { value: 'asia', label: 'Asia' },
  { value: 'latin_america', label: 'Latin America' },
  { value: 'middle_east', label: 'Middle East' },
  { value: 'africa', label: 'Africa' }
]

function formatDate(date) {
  return date.toISOString().split('T')[0]
}

function shiftDays(baseDate, offsetDays) {
  const date = new Date(baseDate)
  date.setDate(date.getDate() + offsetDays)
  return date
}

function getDefaultCollectionWindow() {
  const end = new Date()
  const start = new Date()
  start.setFullYear(start.getFullYear() - 1)
  return {
    startDate: formatDate(start),
    endDate: formatDate(end)
  }
}

function getDefaultTrainingWindow() {
  const today = new Date()
  const testEndDate = formatDate(today)
  const testStartDate = formatDate(shiftDays(today, -60))
  const trainEndDate = formatDate(shiftDays(shiftDays(today, -60), -1))
  const trainStartDate = formatDate(shiftDays(shiftDays(today, -60), -181))

  return {
    trainStart: trainStartDate,
    trainEnd: trainEndDate,
    testStart: testStartDate,
    testEnd: testEndDate
  }
}

function parseNumber(value, fallback) {
  if (value === '' || value === null || value === undefined) {
    return fallback
  }
  const parsed = Number(value)
  return Number.isFinite(parsed) ? parsed : fallback
}

export default function JobCreationModal({
  isOpen,
  onClose,
  initialDatasets = [],
  initialJobType = 'data_collection',
  initialDataJobId = ''
}) {
  const { data: jobs } = useJobs()
  const createJob = useCreateJob()

  const [{ startDate: defaultStart, endDate: defaultEnd }] = useState(getDefaultCollectionWindow)
  const [
    {
      trainStart: defaultTrainStart,
      trainEnd: defaultTrainEnd,
      testStart: defaultTestStart,
      testEnd: defaultTestEnd
    }
  ] = useState(getDefaultTrainingWindow)

  const [jobType, setJobType] = useState(initialJobType || 'data_collection')
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')

  const [region, setRegion] = useState('')
  const [countries, setCountries] = useState('')
  const [startDate, setStartDate] = useState(defaultStart)
  const [endDate, setEndDate] = useState(defaultEnd)

  const [dataJobId, setDataJobId] = useState(initialDataJobId ? String(initialDataJobId) : '')
  const [trainStart, setTrainStart] = useState(defaultTrainStart)
  const [trainEnd, setTrainEnd] = useState(defaultTrainEnd)
  const [testStart, setTestStart] = useState(defaultTestStart)
  const [testEnd, setTestEnd] = useState(defaultTestEnd)
  const [modelType, setModelType] = useState('temporal_attention')
  const [epochs, setEpochs] = useState('25')
  const [sequenceLength, setSequenceLength] = useState('30')
  const [batchSize, setBatchSize] = useState('32')
  const [learningRate, setLearningRate] = useState('0.001')
  const [dropout, setDropout] = useState('0.1')

  const [formError, setFormError] = useState(null)
  const [selectedDatasets, setSelectedDatasets] = useState([])
  const [catalogueFilterTerm, setCatalogueFilterTerm] = useState('')

  const normalizeDatasets = useCallback((items) => {
    const map = new Map()
    ;(items || []).forEach((item) => {
      if (!item || typeof item.id === 'undefined' || item.id === null) {
        return
      }
      map.set(item.id, {
        id: item.id,
        code: item.code || `Dataset ${item.id}`,
        name: item.name || item.code || `Dataset ${item.id}`,
        category: item.category || '',
        region: item.region || '',
        sourceId: item.data_source_id ?? item.data_source?.id ?? null,
        sourceName: item.data_source?.name || item.source_name || 'Catalogue',
        frequency: item.frequency || '',
        unit: item.unit || ''
      })
    })
    return Array.from(map.values())
  }, [])

  const resetForm = useCallback(() => {
    setJobType('data_collection')
    setName('')
    setDescription('')

    const collectionDefaults = getDefaultCollectionWindow()
    setRegion('')
    setCountries('')
    setStartDate(collectionDefaults.startDate)
    setEndDate(collectionDefaults.endDate)

    const trainingDefaults = getDefaultTrainingWindow()
    setDataJobId('')
    setTrainStart(trainingDefaults.trainStart)
    setTrainEnd(trainingDefaults.trainEnd)
    setTestStart(trainingDefaults.testStart)
    setTestEnd(trainingDefaults.testEnd)
    setModelType('temporal_attention')
    setEpochs('25')
    setSequenceLength('30')
    setBatchSize('32')
    setLearningRate('0.001')
    setDropout('0.1')
    setFormError(null)
    setSelectedDatasets([])
    setCatalogueFilterTerm('')
  }, [])

  useEffect(() => {
    if (!isOpen) {
      return
    }
    setFormError(null)
    setCatalogueFilterTerm('')
    setSelectedDatasets(normalizeDatasets(initialDatasets))
    setJobType(initialJobType || 'data_collection')
    setDataJobId(initialDataJobId ? String(initialDataJobId) : '')
  }, [isOpen, initialDatasets, normalizeDatasets, initialJobType, initialDataJobId])

  useEffect(() => {
    setFormError(null)
  }, [jobType])

  const handleClose = useCallback(() => {
    resetForm()
    onClose?.()
  }, [resetForm, onClose])

  const dataCollectionJobs = useMemo(() => {
    if (!jobs) return []
    return jobs
      .filter(
        (job) =>
          (job.job_type === 'data_collection' || job.jobType === 'data_collection') &&
          job.status === 'completed'
      )
      .sort((a, b) => (b.id || b.job_id || 0) - (a.id || a.job_id || 0))
  }, [jobs])

  const handleRemoveDataset = useCallback((datasetId) => {
    setSelectedDatasets((prev) => prev.filter((dataset) => dataset.id !== datasetId))
  }, [])

  const handleClearDatasets = useCallback(() => {
    setSelectedDatasets([])
  }, [])

  const catalogueFilters = useMemo(() => {
    const filters = {}
    if (region) {
      filters.region = region
    }
    filters.enabled_only = true
    return filters
  }, [region])

  const { data: catalogueMatches = [], isLoading: isCatalogueLoading } = useCatalogueItems(
    catalogueFilters,
    { enabled: true, staleTime: 300_000 }
  )

  const normalizedCatalogueOptions = useMemo(
    () => normalizeDatasets(catalogueMatches),
    [catalogueMatches, normalizeDatasets]
  )

  const groupedCatalogueOptions = useMemo(() => {
    const groups = new Map()
    normalizedCatalogueOptions.forEach((dataset) => {
      const key = dataset.sourceName || 'Catalogue'
      if (!groups.has(key)) {
        groups.set(key, [])
      }
      groups.get(key).push(dataset)
    })

    return Array.from(groups.entries())
      .map(([groupName, items]) => [
        groupName,
        items.sort((a, b) => a.name.localeCompare(b.name))
      ])
      .sort(([groupA], [groupB]) => groupA.localeCompare(groupB))
  }, [normalizedCatalogueOptions])

  const filteredCatalogueOptions = useMemo(() => {
    const term = catalogueFilterTerm.trim().toLowerCase()
    if (!term) {
      return groupedCatalogueOptions
    }

    return groupedCatalogueOptions
      .map(([groupName, items]) => [
        groupName,
        items.filter((dataset) => {
          const haystack = `${dataset.code} ${dataset.name} ${dataset.category} ${dataset.region}`.toLowerCase()
          return haystack.includes(term)
        })
      ])
      .filter(([, items]) => items.length > 0)
  }, [groupedCatalogueOptions, catalogueFilterTerm])

  const filteredDatasetCount = useMemo(
    () => filteredCatalogueOptions.reduce((total, [, items]) => total + items.length, 0),
    [filteredCatalogueOptions]
  )

  const filteredSelectedCount = useMemo(() => {
    const selectedIds = new Set(selectedDatasets.map((dataset) => dataset.id))
    return filteredCatalogueOptions.reduce(
      (total, [, items]) => total + items.filter((dataset) => selectedIds.has(dataset.id)).length,
      0
    )
  }, [filteredCatalogueOptions, selectedDatasets])

  const isDatasetSelected = useCallback(
    (datasetId) => selectedDatasets.some((dataset) => dataset.id === datasetId),
    [selectedDatasets]
  )

  const handleToggleDataset = useCallback((dataset) => {
    if (!dataset || typeof dataset.id === 'undefined' || dataset.id === null) {
      return
    }
    const [normalized] = normalizeDatasets([dataset])
    if (!normalized) {
      return
    }
    setSelectedDatasets((prev) => {
      const exists = prev.some((item) => item.id === normalized.id)
      if (exists) {
        return prev.filter((item) => item.id !== normalized.id)
      }
      return [...prev, normalized]
    })
  }, [normalizeDatasets])

  const handleSelectAllFiltered = useCallback(() => {
    const items = filteredCatalogueOptions.flatMap(([, groupItems]) => groupItems)
    if (items.length === 0) {
      return
    }
    setSelectedDatasets((prev) => {
      const map = new Map(prev.map((dataset) => [dataset.id, dataset]))
      items.forEach((dataset) => {
        if (!dataset || typeof dataset.id === 'undefined' || dataset.id === null) {
          return
        }
        const [normalized] = normalizeDatasets([dataset])
        if (normalized) {
          map.set(normalized.id, normalized)
        }
      })
      return Array.from(map.values())
    })
  }, [filteredCatalogueOptions, normalizeDatasets])

  const handleClearFiltered = useCallback(() => {
    const ids = new Set(
      filteredCatalogueOptions.flatMap(([, groupItems]) => groupItems.map((dataset) => dataset.id))
    )
    if (ids.size === 0) {
      return
    }
    setSelectedDatasets((prev) => prev.filter((dataset) => !ids.has(dataset.id)))
  }, [filteredCatalogueOptions])

  const handleSubmit = async (event) => {
    event.preventDefault()
    setFormError(null)

    try {
      const payload = {
        name: name.trim() || `${jobType === 'data_collection' ? 'Data Collection' : 'Model Training'} ${new Date().toISOString().split('T')[0]}`,
        description: description.trim() || undefined,
        job_type: jobType,
        parameters: {},
        scheduled: false
      }

      if (jobType === 'data_collection') {
        const params = {}
        if (region) {
          params.regions = [region]
        }
        const countriesList = countries
          .split(',')
          .map((c) => c.trim())
          .filter(Boolean)
        if (countriesList.length > 0) {
          params.countries = countriesList
        }
        if (startDate) {
          params.start_date = startDate
        }
        if (endDate) {
          params.end_date = endDate
        }
        if (selectedDatasets.length > 0) {
          params.catalogue_items = selectedDatasets.map((dataset) => dataset.id)
        }
        payload.parameters = params
      } else if (jobType === 'training') {
        if (!dataJobId) {
          setFormError('Select a completed data collection job to train on.')
          return
        }

        if (!trainStart || !trainEnd || !testStart || !testEnd) {
          setFormError('Provide training and test date ranges.')
          return
        }

        const params = {
          data_job_id: Number(dataJobId),
          train_start: trainStart,
          train_end: trainEnd,
          test_start: testStart,
          test_end: testEnd,
          config: {
            model: modelType,
            epochs: parseNumber(epochs, 25),
            sequence_length: parseNumber(sequenceLength, 30),
            batch_size: parseNumber(batchSize, 32),
            learning_rate: parseNumber(learningRate, 0.001),
            dropout: parseNumber(dropout, 0.1)
          }
        }

        payload.parameters = params
      }

      await createJob.mutateAsync(payload)
      handleClose()
    } catch (error) {
      setFormError(error.message || 'Failed to create job. Please try again.')
    }
  }

  return (
    <Modal
      isOpen={isOpen}
      onClose={handleClose}
      title="Create New Job"
      footer={
        <>
          <Button type="button" variant="ghost" onClick={handleClose}>
            Cancel
          </Button>
          <Button
            type="submit"
            variant="primary"
            loading={createJob.isPending}
            form="job-create-form"
          >
            Create Job
          </Button>
        </>
      }
    >
      <form id="job-create-form" className="space-y-5" onSubmit={handleSubmit}>
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
          <label className="flex flex-col gap-2">
            <span className="text-sm font-medium text-bne-steel">Job Type</span>
            <select
              className="rounded-lg border border-bne-frost bg-white px-3 py-2 text-sm text-bne-ink focus:border-bne-azure focus:outline-none focus:ring-2 focus:ring-bne-azure"
              value={jobType}
              onChange={(event) => setJobType(event.target.value)}
            >
              {JOB_TYPES.map((type) => (
                <option key={type.value} value={type.value}>
                  {type.label}
                </option>
              ))}
            </select>
          </label>

          <label className="flex flex-col gap-2">
            <span className="text-sm font-medium text-bne-steel">Job Name</span>
            <input
              type="text"
              value={name}
              onChange={(event) => setName(event.target.value)}
              placeholder="Liquidity Data Run"
              className="rounded-lg border border-bne-frost px-3 py-2 text-sm text-bne-ink focus:border-bne-azure focus:outline-none focus:ring-2 focus:ring-bne-azure"
            />
          </label>
        </div>

        <label className="flex flex-col gap-2">
          <span className="text-sm font-medium text-bne-steel">Description</span>
          <textarea
            value={description}
            onChange={(event) => setDescription(event.target.value)}
            rows={3}
            placeholder="Optional context for the team."
            className="rounded-lg border border-bne-frost px-3 py-2 text-sm text-bne-ink focus:border-bne-azure focus:outline-none focus:ring-2 focus:ring-bne-azure"
          />
        </label>

        <div className="rounded-xl border border-bne-frost bg-bne-ice/50 p-4">
          <h3 className="text-sm font-semibold text-bne-ink mb-3">Job Settings</h3>
          {JOB_TYPES.map(
            (type) =>
              type.value === jobType && (
                <p key={type.value} className="text-xs text-bne-steel mb-4">
                  {type.description}
                </p>
              )
          )}

          {jobType === 'data_collection' ? (
            <div className="space-y-4">
              <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
                <label className="flex flex-col gap-2">
                  <span className="text-sm font-medium text-bne-steel">Region</span>
                  <select
                    value={region}
                    onChange={(event) => setRegion(event.target.value)}
                    className="rounded-lg border border-bne-frost bg-white px-3 py-2 text-sm text-bne-ink focus:border-bne-azure focus:outline-none focus:ring-2 focus:ring-bne-azure"
                  >
                    {REGION_OPTIONS.map((option) => (
                      <option key={option.value || 'all'} value={option.value}>
                        {option.label}
                      </option>
                    ))}
                  </select>
                </label>

                <label className="flex flex-col gap-2">
                  <span className="text-sm font-medium text-bne-steel">Countries</span>
                  <input
                    type="text"
                    value={countries}
                    onChange={(event) => setCountries(event.target.value)}
                    placeholder="Comma separated (e.g. United States, Canada)"
                    className="rounded-lg border border-bne-frost px-3 py-2 text-sm text-bne-ink focus:border-bne-azure focus:outline-none focus:ring-2 focus:ring-bne-azure"
                  />
                </label>
              </div>

              <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
                <label className="flex flex-col gap-2">
                  <span className="text-sm font-medium text-bne-steel">Start Date</span>
                  <input
                    type="date"
                    value={startDate}
                    onChange={(event) => setStartDate(event.target.value)}
                    className="rounded-lg border border-bne-frost px-3 py-2 text-sm text-bne-ink focus:border-bne-azure focus:outline-none focus:ring-2 focus:ring-bne-azure"
                  />
                </label>

                <label className="flex flex-col gap-2">
                  <span className="text-sm font-medium text-bne-steel">End Date</span>
                  <input
                    type="date"
                    value={endDate}
                    onChange={(event) => setEndDate(event.target.value)}
                    className="rounded-lg border border-bne-frost px-3 py-2 text-sm text-bne-ink focus:border-bne-azure focus:outline-none focus:ring-2 focus:ring-bne-azure"
                  />
                </label>
              </div>

              <div className="space-y-3">
                <div className="flex items-center justify-between">
                  <span className="text-sm font-medium text-bne-steel">
                    Selected Datasets ({selectedDatasets.length})
                  </span>
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    onClick={handleClearDatasets}
                    disabled={selectedDatasets.length === 0}
                  >
                    Clear
                  </Button>
                </div>

                {selectedDatasets.length > 0 ? (
                  <div className="rounded-lg border border-bne-frost bg-white/70 max-h-44 overflow-y-auto">
                    {selectedDatasets.map((dataset) => (
                      <div
                        key={dataset.id}
                        className="flex items-start justify-between gap-3 px-3 py-2 border-b border-bne-frost last:border-b-0"
                      >
                        <div>
                          <p className="text-sm font-medium text-bne-ink">{dataset.code}</p>
                          <p className="text-xs text-bne-steel">{dataset.name}</p>
                          <p className="text-[11px] text-bne-steel/80 mt-1">
                            {dataset.category ? dataset.category.replace(/_/g, ' ') : '—'} ·{' '}
                            {dataset.region ? dataset.region.replace(/_/g, ' ') : '—'}
                          </p>
                        </div>
                        <Button
                          type="button"
                          variant="ghost"
                          size="sm"
                          onClick={() => handleRemoveDataset(dataset.id)}
                        >
                          Remove
                        </Button>
                      </div>
                    ))}
                  </div>
                ) : (
                  <p className="text-xs text-bne-steel">
                    Nothing selected yet. Use the catalogue list below or jump to Data Sources → “View Data” to pin datasets first.
                  </p>
                )}

                <div className="space-y-2">
                  <label className="flex flex-col gap-2">
                    <span className="text-xs font-semibold uppercase text-bne-steel">
                      Catalogue
                    </span>
                    <input
                      type="search"
                      value={catalogueFilterTerm}
                      onChange={(event) => setCatalogueFilterTerm(event.target.value)}
                      placeholder="Filter by name, code, category, or region"
                      className="rounded-lg border border-bne-frost px-3 py-2 text-sm text-bne-ink focus:border-bne-azure focus:outline-none focus:ring-2 focus:ring-bne-azure"
                    />
                  </label>

                  {isCatalogueLoading ? (
                    <p className="text-sm text-bne-steel">Loading catalogue…</p>
                  ) : filteredCatalogueOptions.length === 0 ? (
                    <p className="text-sm text-bne-crimson/80">
                      No datasets match “{catalogueFilterTerm.trim()}”.
                    </p>
                  ) : (
                    <div className="rounded-lg border border-bne-frost bg-white shadow-sm">
                      <div className="flex flex-col gap-2 border-b border-bne-frost px-3 py-2 md:flex-row md:items-center md:justify-between">
                        <span className="text-xs text-bne-steel">
                          Showing {filteredDatasetCount} dataset{filteredDatasetCount === 1 ? '' : 's'}
                        </span>
                        <div className="flex flex-wrap items-center gap-2">
                          <Button
                            type="button"
                            variant="ghost"
                            size="sm"
                            onClick={handleSelectAllFiltered}
                            disabled={filteredDatasetCount === 0 || filteredDatasetCount === filteredSelectedCount}
                          >
                            Select all shown
                          </Button>
                          <Button
                            type="button"
                            variant="ghost"
                            size="sm"
                            onClick={handleClearFiltered}
                            disabled={filteredSelectedCount === 0}
                          >
                            Clear shown
                          </Button>
                        </div>
                      </div>
                      <div className="max-h-60 overflow-y-auto px-3 py-3 space-y-4">
                        {filteredCatalogueOptions.map(([groupName, items]) => (
                          <div key={groupName} className="space-y-2">
                            <p className="text-xs font-semibold uppercase tracking-wide text-bne-steel">
                              {groupName}
                            </p>
                            <div className="space-y-1.5">
                              {items.map((dataset) => {
                                const checked = isDatasetSelected(dataset.id)
                                return (
                                  <label
                                    key={dataset.id}
                                    className="flex items-start gap-2 rounded-lg border border-transparent px-2 py-1.5 hover:border-bne-azure hover:bg-bne-azure/5"
                                  >
                                    <input
                                      type="checkbox"
                                      className="mt-1 h-4 w-4 rounded border-bne-frost text-bne-azure focus:ring-bne-azure"
                                      checked={checked}
                                      onChange={() => handleToggleDataset(dataset)}
                                    />
                                    <div className="flex-1">
                                      <p className="text-sm font-medium text-bne-ink">{dataset.code}</p>
                                      <p className="text-xs text-bne-steel">{dataset.name}</p>
                                      <p className="text-[11px] text-bne-steel/75 mt-1">
                                        {(dataset.category ? dataset.category.replace(/_/g, ' ') : '—')} ·{' '}
                                        {(dataset.region ? dataset.region.replace(/_/g, ' ') : '—')} {dataset.frequency ? `· ${dataset.frequency}` : ''}{' '}
                                        {dataset.unit ? `· ${dataset.unit}` : ''}
                                      </p>
                                    </div>
                                  </label>
                                )
                              })}
                            </div>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}
                </div>
              </div>

              <p className="text-xs text-bne-steel">
                Leave the dataset list empty to use the default catalogue selection configured in the backend.
              </p>
            </div>
          ) : (
            <div className="space-y-4">
              <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
                <label className="flex flex-col gap-2">
                  <span className="text-sm font-medium text-bne-steel">Data Collection Job</span>
                  <select
                    value={dataJobId}
                    onChange={(event) => setDataJobId(event.target.value)}
                    className="rounded-lg border border-bne-frost bg-white px-3 py-2 text-sm text-bne-ink focus:border-bne-azure focus:outline-none focus:ring-2 focus:ring-bne-azure"
                  >
                    <option value="">Select completed data job</option>
                    {dataCollectionJobs.map((job) => (
                      <option key={job.id || job.job_id} value={job.id || job.job_id}>
                        #{job.id || job.job_id} · {job.name || job.parameters?.regions?.join(', ') || 'Data Collection'}
                      </option>
                    ))}
                  </select>
                  {dataCollectionJobs.length === 0 && (
                    <span className="text-xs text-bne-crimson">
                      No completed data collection jobs available. Run one first.
                    </span>
                  )}
                </label>

                <label className="flex flex-col gap-2">
                  <span className="text-sm font-medium text-bne-steel">Model Type</span>
                  <select
                    value={modelType}
                    onChange={(event) => setModelType(event.target.value)}
                    className="rounded-lg border border-bne-frost bg-white px-3 py-2 text-sm text-bne-ink focus:border-bne-azure focus:outline-none focus:ring-2 focus:ring-bne-azure"
                  >
                    <option value="temporal_attention">Temporal Attention</option>
                    <option value="hgt">Heterogeneous Graph Transformer</option>
                    <option value="lstm">LSTM</option>
                  </select>
                  <p className="text-xs text-bne-steel leading-snug">
                    {MODEL_TYPE_DESCRIPTIONS[modelType] ?? 'Select the architecture that best matches your data relationships.'}
                  </p>
                </label>
              </div>

              <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
                <label className="flex flex-col gap-2">
                  <span className="text-sm font-medium text-bne-steel">Train Period Start</span>
                  <input
                    type="date"
                    value={trainStart}
                    onChange={(event) => setTrainStart(event.target.value)}
                    className="rounded-lg border border-bne-frost px-3 py-2 text-sm text-bne-ink focus:border-bne-azure focus:outline-none focus:ring-2 focus:ring-bne-azure"
                  />
                </label>
                <label className="flex flex-col gap-2">
                  <span className="text-sm font-medium text-bne-steel">Train Period End</span>
                  <input
                    type="date"
                    value={trainEnd}
                    onChange={(event) => setTrainEnd(event.target.value)}
                    className="rounded-lg border border-bne-frost px-3 py-2 text-sm text-bne-ink focus:border-bne-azure focus:outline-none focus:ring-2 focus:ring-bne-azure"
                  />
                </label>
              </div>

              <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
                <label className="flex flex-col gap-2">
                  <span className="text-sm font-medium text-bne-steel">Test Period Start</span>
                  <input
                    type="date"
                    value={testStart}
                    onChange={(event) => setTestStart(event.target.value)}
                    className="rounded-lg border border-bne-frost px-3 py-2 text-sm text-bne-ink focus:border-bne-azure focus:outline-none focus:ring-2 focus:ring-bne-azure"
                  />
                </label>
                <label className="flex flex-col gap-2">
                  <span className="text-sm font-medium text-bne-steel">Test Period End</span>
                  <input
                    type="date"
                    value={testEnd}
                    onChange={(event) => setTestEnd(event.target.value)}
                    className="rounded-lg border border-bne-frost px-3 py-2 text-sm text-bne-ink focus:border-bne-azure focus:outline-none focus:ring-2 focus:ring-bne-azure"
                  />
                </label>
              </div>

              <div className="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-3">
                <label className="flex flex-col gap-2">
                  <span className="text-sm font-medium text-bne-steel">Epochs</span>
                  <input
                    type="number"
                    min="1"
                    value={epochs}
                    onChange={(event) => setEpochs(event.target.value)}
                    className="rounded-lg border border-bne-frost px-3 py-2 text-sm text-bne-ink focus:border-bne-azure focus:outline-none focus:ring-2 focus:ring-bne-azure"
                  />
                </label>
                <label className="flex flex-col gap-2">
                  <span className="text-sm font-medium text-bne-steel">Sequence Length</span>
                  <input
                    type="number"
                    min="1"
                    value={sequenceLength}
                    onChange={(event) => setSequenceLength(event.target.value)}
                    className="rounded-lg border border-bne-frost px-3 py-2 text-sm text-bne-ink focus:border-bne-azure focus:outline-none focus:ring-2 focus:ring-bne-azure"
                  />
                </label>
                <label className="flex flex-col gap-2">
                  <span className="text-sm font-medium text-bne-steel">Batch Size</span>
                  <input
                    type="number"
                    min="1"
                    value={batchSize}
                    onChange={(event) => setBatchSize(event.target.value)}
                    className="rounded-lg border border-bne-frost px-3 py-2 text-sm text-bne-ink focus:border-bne-azure focus:outline-none focus:ring-2 focus:ring-bne-azure"
                  />
                </label>
              </div>

              <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
                <label className="flex flex-col gap-2">
                  <span className="text-sm font-medium text-bne-steel">Learning Rate</span>
                  <input
                    type="number"
                    step="0.0001"
                    min="0"
                    value={learningRate}
                    onChange={(event) => setLearningRate(event.target.value)}
                    className="rounded-lg border border-bne-frost px-3 py-2 text-sm text-bne-ink focus:border-bne-azure focus:outline-none focus:ring-2 focus:ring-bne-azure"
                  />
                </label>
                <label className="flex flex-col gap-2">
                  <span className="text-sm font-medium text-bne-steel">Dropout</span>
                  <input
                    type="number"
                    step="0.01"
                    min="0"
                    max="1"
                    value={dropout}
                    onChange={(event) => setDropout(event.target.value)}
                    className="rounded-lg border border-bne-frost px-3 py-2 text-sm text-bne-ink focus:border-bne-azure focus:outline-none focus:ring-2 focus:ring-bne-azure"
                  />
                </label>
              </div>
            </div>
          )}
        </div>

        {formError && (
          <div className="rounded-lg border border-bne-crimson/40 bg-bne-crimson/10 px-4 py-3 text-sm text-bne-crimson">
            {formError}
          </div>
        )}
      </form>
    </Modal>
  )
}

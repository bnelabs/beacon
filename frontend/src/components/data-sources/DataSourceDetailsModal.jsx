import { useEffect, useMemo, useState } from 'react'
import Modal from '../ui/Modal'
import Button from '../ui/Button'
import LoadingSpinner from '../ui/LoadingSpinner'
import { useCatalogueItems } from '../../hooks/useApi'

export default function DataSourceDetailsModal({
  isOpen,
  source,
  onClose,
  preselectedDatasetIds = [],
  onApplySelection
}) {
  const sourceId = source?.id || source?.source_id
  const [searchTerm, setSearchTerm] = useState('')
  const [regionFilter, setRegionFilter] = useState('all')
  const [countryFilter, setCountryFilter] = useState('all')
  const [previewDataset, setPreviewDataset] = useState(null)

  const filters = useMemo(() => {
    if (!sourceId) {
      return { enabled_only: false }
    }
    return {
      sources: [String(sourceId)],
      enabled_only: false
    }
  }, [sourceId])

  const { data: catalogueItems, isLoading, error } = useCatalogueItems(filters, {
    enabled: isOpen && !!sourceId,
    staleTime: 5 * 60_000
  })

  const [selectedIds, setSelectedIds] = useState(() => new Set(preselectedDatasetIds))

  useEffect(() => {
    if (!isOpen) {
      return
    }
    setSearchTerm('')
    setRegionFilter('all')
    setCountryFilter('all')
    setPreviewDataset(null)
    setSelectedIds(new Set(preselectedDatasetIds))
  }, [isOpen, preselectedDatasetIds])

  const toggleDataset = (datasetId) => {
    setSelectedIds((prev) => {
      const next = new Set(prev)
      if (next.has(datasetId)) {
        next.delete(datasetId)
      } else {
        next.add(datasetId)
      }
      return next
    })
  }

  const selectAll = () => {
    if (!catalogueItems) return
    setSelectedIds(new Set(catalogueItems.map((item) => item.id)))
  }

  const clearSelection = () => {
    setSelectedIds(new Set())
  }

  const selectedDatasets = useMemo(() => {
    if (!catalogueItems) return []
    return catalogueItems
      .filter((item) => selectedIds.has(item.id))
      .map((item) => ({
        id: item.id,
        code: item.code,
        name: item.name,
        category: item.category,
        region: item.region
      }))
  }, [catalogueItems, selectedIds])

  const regions = useMemo(() => {
    if (!catalogueItems) return []
    const unique = new Set()
    catalogueItems.forEach((item) => {
      if (item.region) {
        unique.add(item.region)
      }
    })
    return Array.from(unique.values()).sort()
  }, [catalogueItems])

  const countries = useMemo(() => {
    if (!catalogueItems) return []
    const unique = new Set()
    catalogueItems.forEach((item) => {
      if (item.country_code || item.country) {
        unique.add(item.country_code || item.country)
      }
    })
    return Array.from(unique.values()).sort()
  }, [catalogueItems])

  const filteredItems = useMemo(() => {
    if (!catalogueItems) return []
    return catalogueItems.filter((item) => {
      const matchesSearch = !searchTerm
        || item.code?.toLowerCase().includes(searchTerm.toLowerCase())
        || item.name?.toLowerCase().includes(searchTerm.toLowerCase())
        || item.category?.toLowerCase().includes(searchTerm.toLowerCase())
      const matchesRegion = regionFilter === 'all'
        || (item.region && item.region === regionFilter)
      const countryValue = item.country_code || item.country
      const matchesCountry = countryFilter === 'all'
        || (countryValue && countryValue === countryFilter)
      return matchesSearch && matchesRegion && matchesCountry
    })
  }, [catalogueItems, searchTerm, regionFilter, countryFilter])

  const datasetSummary = useMemo(() => {
    const total = filteredItems.length
    const regionsCount = new Map()
    filteredItems.forEach((item) => {
      const key = item.region || 'Unspecified'
      regionsCount.set(key, (regionsCount.get(key) || 0) + 1)
    })
    return {
      total,
      regions: Array.from(regionsCount.entries())
        .sort((a, b) => b[1] - a[1])
        .slice(0, 4)
    }
  }, [filteredItems])

  const handleApplySelection = () => {
    if (onApplySelection) {
      if (previewDataset) {
        setPreviewDataset(null)
      }
      onApplySelection(selectedDatasets)
    }
  }

  const selectionCount = selectedDatasets.length
  const allSelected = catalogueItems && catalogueItems.length > 0 && selectionCount === catalogueItems.length

  if (!source) {
    return null
  }

  const metadata = [
    { label: 'Status', value: source.status },
    { label: 'Plugin Type', value: source.plugin_type },
    { label: 'Enabled', value: source.enabled ? 'Yes' : 'No' },
    { label: 'Created', value: source.created_at ? new Date(source.created_at).toLocaleString() : '—' },
    { label: 'Last Updated', value: source.updated_at ? new Date(source.updated_at).toLocaleString() : '—' },
    {
      label: 'Last Successful Fetch',
      value: source.last_successful_fetch ? new Date(source.last_successful_fetch).toLocaleString() : 'Never'
    },
    { label: 'Registration URL', value: source.registration_url || '—' },
    { label: 'Free Tier Limits', value: source.free_tier_limits || '—' },
    { label: 'Coverage', value: source.coverage_description || '—' }
  ]

  const configJson = (() => {
    try {
      return JSON.stringify(source.config ?? {}, null, 2)
    } catch (error) {
      return '{}'
    }
  })()

  return (
    <Modal
      isOpen={isOpen}
      onClose={onClose}
      title={`Data Source · ${source.name}`}
      widthClass="max-w-4xl"
      footer={
        <Button type="button" onClick={onClose}>
          Close
        </Button>
      }
    >
      <div className="space-y-5">
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {metadata.map((item) => (
            <div key={item.label}>
              <p className="text-xs uppercase tracking-wide text-bne-steel">{item.label}</p>
              <p className="text-sm font-medium text-bne-ink mt-1 break-words">{item.value}</p>
            </div>
          ))}
        </div>

        {source.error_message && (
          <div className="rounded-lg border border-bne-crimson/30 bg-bne-crimson/10 px-4 py-3 text-sm text-bne-crimson">
            <strong className="block mb-1">Last error</strong>
            <span className="font-mono">{source.error_message}</span>
          </div>
        )}

        <div>
          <p className="text-xs uppercase tracking-wide text-bne-steel mb-2">Configuration</p>
          <pre className="max-h-64 overflow-auto rounded-lg border border-bne-frost bg-bne-ice/60 p-4 text-xs text-bne-ink font-mono">
            {configJson}
          </pre>
        </div>

        <div>
          <p className="text-xs uppercase tracking-wide text-bne-steel mb-2">Available Datasets</p>
          {isLoading ? (
            <div className="flex justify-center py-6">
              <LoadingSpinner message="Loading datasets..." />
            </div>
          ) : error ? (
            <div className="rounded-lg border border-bne-crimson/30 bg-bne-crimson/10 px-4 py-3 text-sm text-bne-crimson">
              Failed to load datasets: {error.message}
            </div>
          ) : catalogueItems && catalogueItems.length > 0 ? (
            <>
              <div className="grid grid-cols-1 lg:grid-cols-5 gap-3 mb-4">
                <div className="lg:col-span-2">
                  <label className="block text-xs uppercase tracking-wide text-bne-steel mb-1">
                    Search datasets
                  </label>
                  <input
                    type="search"
                    value={searchTerm}
                    onChange={(event) => setSearchTerm(event.target.value)}
                    placeholder="Filter by code, name, or category"
                    className="w-full px-3 py-2 border border-bne-frost rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-bne-azure"
                  />
                </div>
                <div>
                  <label className="block text-xs uppercase tracking-wide text-bne-steel mb-1">
                    Region
                  </label>
                  <select
                    value={regionFilter}
                    onChange={(event) => setRegionFilter(event.target.value)}
                    className="w-full px-3 py-2 border border-bne-frost rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-bne-azure"
                  >
                    <option value="all">All regions</option>
                    {regions.map((region) => (
                      <option key={region} value={region}>
                        {region.replace(/_/g, ' ')}
                      </option>
                    ))}
                  </select>
                </div>
                <div>
                  <label className="block text-xs uppercase tracking-wide text-bne-steel mb-1">
                    Country
                  </label>
                  <select
                    value={countryFilter}
                    onChange={(event) => setCountryFilter(event.target.value)}
                    className="w-full px-3 py-2 border border-bne-frost rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-bne-azure"
                  >
                    <option value="all">All countries</option>
                    {countries.map((country) => (
                      <option key={country} value={country}>
                        {country}
                      </option>
                    ))}
                  </select>
                </div>
                <div className="bg-bne-ice/60 border border-bne-frost rounded-lg p-3">
                  <p className="text-xs uppercase tracking-wide text-bne-steel mb-1">Quick summary</p>
                  <p className="text-lg font-semibold text-bne-ink">{datasetSummary.total}</p>
                  <p className="text-xs text-bne-steel mt-1">
                    datasets match your filters
                  </p>
                </div>
              </div>

              <div className="flex flex-col md:flex-row md:items-center md:justify-between gap-3 mb-3">
                <span className="text-xs text-bne-steel">{selectionCount} selected</span>
                <div className="flex flex-wrap items-center gap-2">
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    onClick={selectAll}
                    disabled={!catalogueItems.length}
                  >
                    Select All
                  </Button>
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    onClick={clearSelection}
                    disabled={selectionCount === 0}
                  >
                    Clear Selection
                  </Button>
                  <Button
                    type="button"
                    variant="primary"
                    size="sm"
                    onClick={() => {
                      handleApplySelection()
                      onClose?.()
                    }}
                    disabled={selectionCount === 0}
                  >
                    Use Selected ({selectionCount})
                  </Button>
                </div>
              </div>

              <div className="max-h-64 overflow-y-auto rounded-lg border border-bne-frost">
                <table className="min-w-full text-sm">
                  <thead className="bg-bne-ice/60 text-bne-steel text-xs uppercase">
                    <tr>
                      <th className="px-2 py-2 text-left">
                        <input
                          type="checkbox"
                          className="h-4 w-4 rounded border-bne-frost text-bne-azure focus:ring-bne-azure"
                          checked={allSelected}
                          onChange={() => (allSelected ? clearSelection() : selectAll())}
                          aria-label="Select all datasets"
                        />
                      </th>
                      <th className="px-3 py-2 text-left">ID</th>
                      <th className="px-3 py-2 text-left">Code</th>
                      <th className="px-3 py-2 text-left">Name</th>
                      <th className="px-3 py-2 text-left">Category</th>
                      <th className="px-3 py-2 text-left">Region</th>
                    </tr>
                  </thead>
                  <tbody>
                    {filteredItems.map((item) => {
                      const isSelected = selectedIds.has(item.id)
                      const isPreviewed = previewDataset && previewDataset.id === item.id
                      return (
                      <tr
                        key={item.id}
                        className={`border-t border-bne-frost cursor-pointer hover:bg-bne-ice/40 ${isPreviewed ? 'bg-bne-ice/60' : ''}`}
                        onClick={() => setPreviewDataset(item)}
                      >
                        <td className="px-2 py-2">
                          <input
                            type="checkbox"
                            className="h-4 w-4 rounded border-bne-frost text-bne-azure focus:ring-bne-azure"
                            checked={isSelected}
                            onChange={() => toggleDataset(item.id)}
                            aria-label={`Select dataset ${item.code}`}
                            onClick={(event) => event.stopPropagation()}
                          />
                        </td>
                        <td className="px-3 py-2 font-mono text-xs text-bne-steel">{item.id}</td>
                        <td className="px-3 py-2 font-mono text-xs text-bne-ink">{item.code}</td>
                        <td className="px-3 py-2 text-bne-ink">{item.name}</td>
                        <td className="px-3 py-2 text-bne-steel text-xs uppercase">{item.category?.replace(/_/g, ' ')}</td>
                        <td className="px-3 py-2 text-bne-steel text-xs uppercase">{item.region?.replace(/_/g, ' ')}</td>
                      </tr>
                    )})}
                  </tbody>
                </table>
              </div>

              {previewDataset && (
                <div className="mt-4 rounded-lg border border-bne-frost bg-bne-ice/40 p-4">
                  <div className="flex items-start justify-between gap-4">
                    <div>
                      <p className="text-xs uppercase tracking-wide text-bne-steel mb-1">
                        Dataset insight
                      </p>
                      <h4 className="text-lg font-semibold text-bne-ink">{previewDataset.name}</h4>
                      <p className="text-xs text-bne-steel mt-1">
                        {previewDataset.code} · {previewDataset.region || 'Global'} · {previewDataset.category?.replace(/_/g, ' ')}
                      </p>
                    </div>
                    <Button
                      type="button"
                      size="sm"
                      variant={selectedIds.has(previewDataset.id) ? 'primary' : 'outline'}
                      onClick={() => {
                        toggleDataset(previewDataset.id)
                      }}
                    >
                      {selectedIds.has(previewDataset.id) ? 'Selected' : 'Add to job'}
                    </Button>
                  </div>
                  <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mt-4 text-sm">
                    <div>
                      <p className="text-xs uppercase tracking-wide text-bne-steel">Country</p>
                      <p className="font-medium text-bne-ink mt-1">
                        {previewDataset.country_code || previewDataset.country || 'Multiple'}
                      </p>
                    </div>
                    <div>
                      <p className="text-xs uppercase tracking-wide text-bne-steel">Frequency</p>
                      <p className="font-medium text-bne-ink mt-1">
                        {previewDataset.frequency || previewDataset.update_frequency || 'Not provided'}
                      </p>
                    </div>
                    <div>
                      <p className="text-xs uppercase tracking-wide text-bne-steel">Latest coverage</p>
                      <p className="font-medium text-bne-ink mt-1">
                        {previewDataset.last_updated || previewDataset.coverage_end || 'Unknown'}
                      </p>
                    </div>
                  </div>
                  {previewDataset.description && (
                    <p className="text-sm text-bne-steel mt-3">
                      {previewDataset.description}
                    </p>
                  )}
                  {previewDataset.sample_metrics && (
                    <div className="mt-4 grid grid-cols-1 md:grid-cols-3 gap-3 text-xs">
                      {Object.entries(previewDataset.sample_metrics).map(([key, value]) => (
                        <div key={key} className="rounded-lg border border-bne-frost bg-white px-3 py-2">
                          <p className="uppercase tracking-wide text-bne-steel">{key.replace(/_/g, ' ')}</p>
                          <p className="text-sm font-semibold text-bne-ink mt-1">{value}</p>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              )}
            </>
          ) : (
            <p className="text-sm text-bne-steel">No datasets registered for this data source yet.</p>
          )}
        </div>
      </div>
    </Modal>
  )
}

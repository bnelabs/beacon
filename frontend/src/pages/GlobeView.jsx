import { useMemo, useState } from 'react'
import { useStore } from '../store/useStore'
import PageContainer from '../components/ui/PageContainer'
import Card from '../components/ui/Card'
import Button from '../components/ui/Button'
import Badge from '../components/ui/Badge'
import GlobeCanvas from '../components/globe/GlobeCanvas'
import { useBanksByRegion } from '../hooks/useApi'
import LoadingSpinner from '../components/ui/LoadingSpinner'
import ErrorMessage from '../components/ui/ErrorMessage'

export default function GlobeView() {
  const { selectedRegion, setSelectedRegion, globeRotation, setGlobeRotation } = useStore()
  const [selectedDataSource, setSelectedDataSource] = useState('fdic')
  const regionFilters = useMemo(() => {
    if (!selectedRegion) return null

    const { country, name, id } = selectedRegion

    const countryIsoMap = {
      USA: 'USA',
      US: 'USA',
      UK: 'GBR',
      UnitedKingdom: 'GBR',
      Germany: 'DEU',
      France: 'FRA',
      Italy: 'ITA',
      Spain: 'ESP',
      Japan: 'JPN',
      China: 'CHN',
      Singapore: 'SGP',
      Australia: 'AUS'
    }

    const filters = { enabled_only: true }

    const normalizedCountry = country?.replace(/\s+/g, '')
    const iso = countryIsoMap[country] || countryIsoMap[normalizedCountry]

    if (iso) {
      filters.countries = [iso]
    }

    const regionMap = {
      'us-northeast': 'north_america',
      'us-southeast': 'north_america',
      'us-midwest': 'north_america',
      'us-southwest': 'north_america',
      'us-west': 'north_america',
      uk: 'europe',
      germany: 'europe',
      france: 'europe',
      italy: 'europe',
      spain: 'europe',
      japan: 'asia',
      china: 'asia',
      singapore: 'asia',
      australia: 'asia'
    }

    const regionKey = regionMap[id] || regionMap[name?.toLowerCase?.()] || null
    if (regionKey) {
      filters.region = regionKey
    }

    return filters
  }, [selectedRegion])

  const {
    data: banks = [],
    isFetching: banksLoading,
    error: banksError,
    refetch: refetchBanks
  } = useBanksByRegion(regionFilters)

  const totalAssets = banks.length
  const criticalAssets = useMemo(() => banks.filter((bank) => bank.risk_score && bank.risk_score >= 0.7), [banks])

  return (
    <PageContainer
      title="Globe View"
      actions={
        <div className="flex items-center gap-2">
          <Button
            variant={globeRotation ? 'primary' : 'ghost'}
            size="sm"
            onClick={() => setGlobeRotation(!globeRotation)}
          >
            {globeRotation ? 'Stop Rotation' : 'Auto Rotate'}
          </Button>
          <Button variant="outline" size="sm">
            Reset View
          </Button>
        </div>
      }
    >
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6 h-[calc(100vh-12rem)]">
        <div className="lg:col-span-2">
          <Card className="h-full p-0 overflow-hidden">
            <GlobeCanvas
              onRegionClick={setSelectedRegion}
              selectedRegion={selectedRegion}
              autoRotate={globeRotation}
            />
          </Card>
        </div>

        <div className="space-y-6 overflow-y-auto">
          <Card>
            <h3 className="font-semibold text-bne-ink mb-4">Data Source</h3>
            <div className="space-y-2">
              {['fdic', 'ecb', 'fmp'].map((source) => (
                <button
                  key={source}
                  onClick={() => setSelectedDataSource(source)}
                  className={`w-full text-left px-4 py-3 rounded-lg border-2 transition-all ${
                    selectedDataSource === source
                      ? 'border-bne-azure bg-bne-azure/5'
                      : 'border-bne-frost hover:border-bne-azure/50'
                  }`}
                >
                  <div className="flex items-center justify-between">
                    <span className="font-medium text-bne-ink uppercase">{source}</span>
                    {selectedDataSource === source && (
                      <Badge variant="primary" size="sm">Active</Badge>
                    )}
                  </div>
                </button>
              ))}
            </div>
          </Card>

          {selectedRegion && (
            <Card>
              <h3 className="font-semibold text-bne-ink mb-4">Region Details</h3>
              <div className="space-y-3">
                <div>
                  <p className="text-sm text-bne-steel mb-1">Region</p>
                  <p className="font-medium text-bne-ink">{selectedRegion.name}</p>
                </div>
                <div>
                  <p className="text-sm text-bne-steel mb-1">Country</p>
                  <p className="font-medium text-bne-ink">{selectedRegion.country}</p>
                </div>
                <div>
                  <p className="text-sm text-bne-steel mb-1">Banks</p>
                  <p className="font-medium text-bne-ink">{selectedRegion.bankCount}</p>
                </div>
                <div>
                  <p className="text-sm text-bne-steel mb-1">Coordinates</p>
                  <p className="font-medium text-bne-ink font-mono text-xs">
                    {selectedRegion.lat.toFixed(4)}, {selectedRegion.lon.toFixed(4)}
                  </p>
                </div>
              </div>
              <div className="mt-4 pt-4 border-t border-bne-frost space-y-3">
                <div className="flex items-center justify-between text-sm">
                  <span className="text-bne-steel">Datasets</span>
                  <Badge variant="info" size="sm">{totalAssets}</Badge>
                </div>
                {banksLoading ? (
                  <div className="py-6">
                    <LoadingSpinner message="Loading datasets..." />
                  </div>
                ) : banksError ? (
                  <ErrorMessage
                    title="Failed to load datasets"
                    error={banksError}
                    onRetry={refetchBanks}
                  />
                ) : totalAssets > 0 ? (
                  <div className="space-y-2">
                    <div className="max-h-60 overflow-y-auto rounded-lg border border-bne-frost">
                      <table className="min-w-full text-sm">
                        <thead className="bg-bne-ice/60 text-xs uppercase text-bne-steel">
                          <tr>
                            <th className="px-3 py-2 text-left">Code</th>
                            <th className="px-3 py-2 text-left">Name</th>
                            <th className="px-3 py-2 text-left">Category</th>
                          </tr>
                        </thead>
                        <tbody>
                          {banks.map((bank) => (
                            <tr key={bank.id} className="border-t border-bne-frost">
                              <td className="px-3 py-2 font-mono text-xs text-bne-ink">{bank.code}</td>
                              <td className="px-3 py-2 text-bne-ink">{bank.name}</td>
                              <td className="px-3 py-2 text-xs uppercase text-bne-steel">{bank.category?.replace(/_/g, ' ') || '—'}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                    {criticalAssets.length > 0 && (
                      <p className="text-xs text-bne-crimson">
                        {criticalAssets.length} dataset{criticalAssets.length === 1 ? '' : 's'} flagged with elevated risk (score ≥ 0.7)
                      </p>
                    )}
                  </div>
                ) : (
                  <p className="text-xs text-bne-steel">
                    No datasets found for this region. Try syncing the data source.
                  </p>
                )}
              </div>
            </Card>
          )}

          {!selectedRegion && (
            <Card className="border-2 border-dashed border-bne-frost bg-bne-ice/50">
              <div className="text-center py-8">
                <svg
                  className="w-12 h-12 mx-auto text-bne-steel/50 mb-3"
                  fill="none"
                  viewBox="0 0 24 24"
                  stroke="currentColor"
                >
                  <path
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    strokeWidth={2}
                    d="M15 15l-2 5L9 9l11 4-5 2zm0 0l5 5M7.188 2.239l.777 2.897M5.136 7.965l-2.898-.777M13.95 4.05l-2.122 2.122m-5.657 5.656l-2.12 2.122"
                  />
                </svg>
                <p className="text-sm text-bne-steel">
                  Click on a region marker to view details
                </p>
              </div>
            </Card>
          )}

          <Card>
            <h3 className="font-semibold text-bne-ink mb-4">Quick Stats</h3>
            <div className="space-y-3">
              <div className="flex items-center justify-between">
                <span className="text-sm text-bne-steel">Total Regions</span>
                <Badge variant="info" size="sm">14</Badge>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-sm text-bne-steel">Total Banks</span>
                <Badge variant="primary" size="sm">7,012</Badge>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-sm text-bne-steel">Active Models</span>
                <Badge variant="success" size="sm">3</Badge>
              </div>
            </div>
          </Card>
        </div>
      </div>
    </PageContainer>
  )
}

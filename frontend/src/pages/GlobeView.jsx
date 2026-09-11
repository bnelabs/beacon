import { useMemo, useState } from 'react'
import { useStore } from '../store/useStore'
import PageContainer from '../components/ui/PageContainer'
import Card from '../components/ui/Card'
import Button from '../components/ui/Button'
import Badge from '../components/ui/Badge'
import RiskMap from '../components/map/RiskMap'
import { normalizeNetworkGraph, useBanksByRegion, useNetworkGraph } from '../hooks/useApi'
import LoadingSpinner from '../components/ui/LoadingSpinner'
import ErrorMessage from '../components/ui/ErrorMessage'
import { cn } from '../utils/cn'
import {
  formatExposure,
  getRiskLevel,
  getRiskColor,
  networkConnections
} from '../data/network-connections'
import { regions } from '../data/regions'

// The bundled network file is demo data. It is only consulted when this flag is
// explicitly set AND the backend has nothing to serve, and the fallback is
// labelled in the UI so it cannot be mistaken for live exposures.
const ALLOW_STATIC_NETWORK_FALLBACK =
  import.meta.env.VITE_ALLOW_STATIC_NETWORK_FALLBACK === 'true'

const API_REGION_BY_ID = {
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

const DATA_SOURCES = ['fdic', 'ecb', 'fmp']

export default function RiskMapPage() {
  const { selectedRegion, setSelectedRegion } = useStore()
  const [selectedDataSource, setSelectedDataSource] = useState('fdic')
  const [showNetwork, setShowNetwork] = useState(false)
  const [showHeatmap, setShowHeatmap] = useState(true)
  const [resetToken, setResetToken] = useState(0)
  const [selectedConnection, setSelectedConnection] = useState(null)

  const regionFilters = useMemo(() => {
    if (!selectedRegion) return null

    const filters = { enabled_only: true }
    if (selectedRegion.iso3) {
      filters.countries = [selectedRegion.iso3]
    }

    const regionKey = API_REGION_BY_ID[selectedRegion.id]
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

  const {
    data: networkPayload,
    isLoading: networkLoading,
    isError: networkIsError
  } = useNetworkGraph()

  const network = useMemo(() => normalizeNetworkGraph(networkPayload), [networkPayload])

  const fallbackActive = Boolean(
    ALLOW_STATIC_NETWORK_FALLBACK &&
      !networkLoading &&
      (networkIsError || network.status === 'unavailable') &&
      networkConnections.length > 0
  )

  // Exposures come from the backend. An institution-level edge is only loadable
  // when both endpoints are present in the network payload; nothing is
  // synthesised for edges the API did not send.
  const connections = useMemo(() => {
    if (network.status === 'available') {
      return network.edges.map((edge) => ({
        id: edge.id,
        source: edge.source,
        target: edge.target,
        exposure: Number(edge.exposure),
        riskScore: typeof edge.risk_score === 'number' ? edge.risk_score : null,
        layer: edge.layer,
        kind: edge.kind
      }))
    }
    if (fallbackActive) {
      return networkConnections.map((connection) => ({
        ...connection,
        riskScore: typeof connection.riskScore === 'number' ? connection.riskScore : null
      }))
    }
    return []
  }, [network, fallbackActive])

  const networkSummary = useMemo(() => {
    const totalExposure = connections.reduce(
      (sum, connection) => sum + (Number(connection.exposure) || 0),
      0
    )
    const scored = connections.filter((connection) => typeof connection.riskScore === 'number')
    const averageRisk = scored.length
      ? scored.reduce((sum, connection) => sum + connection.riskScore, 0) / scored.length
      : null
    const riskiest = scored.length
      ? scored.reduce((max, connection) => (connection.riskScore > max.riskScore ? connection : max))
      : null
    const largest = connections.length
      ? connections.reduce((max, connection) =>
          (Number(connection.exposure) || 0) > (Number(max.exposure) || 0) ? connection : max
        )
      : null
    return { totalExposure, averageRisk, riskiest, largest, count: connections.length }
  }, [connections])

  const getRegionName = (regionId) => regions.find((region) => region.id === regionId)?.name || regionId

  const handleConnectionClick = (connection) => {
    setSelectedConnection(connection)
    setSelectedRegion(null)
  }

  const handleRegionSelect = (region) => {
    setSelectedRegion(region)
    setSelectedConnection(null)
  }

  return (
    <PageContainer
      title="Risk Map"
      subtitle="Geographic view of systemic liquidity risk and interbank exposures"
      actions={
        <div className="flex items-center gap-2">
          <Button
            variant={showNetwork ? 'primary' : 'ghost'}
            size="sm"
            onClick={() => setShowNetwork(!showNetwork)}
          >
            {showNetwork ? (
              <>
                <svg className="w-4 h-4 mr-2" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M13.875 18.825A10.05 10.05 0 0112 19c-4.478 0-8.268-2.943-9.543-7a9.97 9.97 0 011.563-3.029m5.858.908a3 3 0 114.243 4.243M9.878 9.878l4.242 4.242M9.88 9.88l-3.29-3.29m7.532 7.532l3.29 3.29M3 3l3.59 3.59m0 0A9.953 9.953 0 0112 5c4.478 0 8.268 2.943 9.543 7a10.025 10.025 0 01-4.132 5.411m0 0L21 21" />
                </svg>
                Hide Network
              </>
            ) : (
              <>
                <svg className="w-4 h-4 mr-2" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M8 16H6a2 2 0 01-2-2V6a2 2 0 012-2h8a2 2 0 012 2v2m-6 12h8a2 2 0 002-2v-8a2 2 0 00-2-2h-8a2 2 0 00-2 2v8a2 2 0 002 2z" />
                </svg>
                Show Network
              </>
            )}
          </Button>
          <Button
            variant={showHeatmap ? 'primary' : 'ghost'}
            size="sm"
            onClick={() => setShowHeatmap(!showHeatmap)}
          >
            {showHeatmap ? 'Hide Heatmap' : 'Show Heatmap'}
          </Button>
          <Button variant="outline" size="sm" onClick={() => setResetToken((token) => token + 1)}>
            Reset View
          </Button>
        </div>
      }
    >
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6 h-[calc(100vh-12rem)]">
        <div className="lg:col-span-2">
          <Card className="h-full p-0 overflow-hidden">
            <RiskMap
              selectedRegion={selectedRegion}
              onRegionSelect={handleRegionSelect}
              showNetwork={showNetwork}
              showHeatmap={showHeatmap}
              banks={banks}
              onConnectionClick={handleConnectionClick}
              resetToken={resetToken}
              allowStaticNetworkFallback={ALLOW_STATIC_NETWORK_FALLBACK}
            />
          </Card>
        </div>

        <div className="space-y-6 overflow-y-auto">
          <Card>
            <h3 className="font-semibold text-bne-ink mb-4">Data Source</h3>
            <div className="space-y-2">
              {DATA_SOURCES.map((source) => (
                <button
                  key={source}
                  onClick={() => setSelectedDataSource(source)}
                  className={cn(
                    'w-full text-left px-4 py-3 rounded-lg border-2 transition-all',
                    selectedDataSource === source
                      ? 'border-bne-azure bg-bne-azure/5'
                      : 'border-bne-frost hover:border-bne-azure/50'
                  )}
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

          <Card>
            <h3 className="font-semibold text-bne-ink mb-4">Regions</h3>
            <div className="flex flex-wrap gap-2">
              {regions.map((region) => (
                <button
                  key={region.id}
                  onClick={() => handleRegionSelect(region)}
                  className={cn(
                    'px-3 py-1.5 rounded-full border text-xs font-medium transition-colors',
                    selectedRegion?.id === region.id
                      ? 'border-bne-azure bg-bne-azure text-white'
                      : 'border-bne-frost text-bne-steel hover:border-bne-azure/50 hover:text-bne-ink'
                  )}
                >
                  {region.name}
                </button>
              ))}
            </div>
          </Card>

          {selectedConnection && (
            <Card>
              <div className="flex items-start justify-between mb-4">
                <h3 className="font-semibold text-bne-ink">Network Connection</h3>
                <button
                  onClick={() => setSelectedConnection(null)}
                  className="text-bne-steel hover:text-bne-ink"
                  aria-label="Close connection details"
                >
                  <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                    <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
                  </svg>
                </button>
              </div>
              <div className="space-y-3">
                <div>
                  <p className="text-xs text-bne-steel mb-1">Source → Target</p>
                  <p className="font-medium text-bne-ink">
                    {getRegionName(selectedConnection.source)} → {getRegionName(selectedConnection.target)}
                  </p>
                </div>
                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <p className="text-xs text-bne-steel mb-1">Exposure</p>
                    <p className="font-semibold text-bne-ink text-lg">
                      {formatExposure(Number(selectedConnection.exposure) || 0)}
                    </p>
                  </div>
                  <div>
                    <p className="text-xs text-bne-steel mb-1">Risk Level</p>
                    {typeof selectedConnection.riskScore === 'number' ? (
                      <Badge
                        variant={
                          selectedConnection.riskScore < 0.3
                            ? 'success'
                            : selectedConnection.riskScore < 0.6
                            ? 'default'
                            : selectedConnection.riskScore < 0.8
                            ? 'warning'
                            : 'danger'
                        }
                      >
                        {getRiskLevel(selectedConnection.riskScore)}
                      </Badge>
                    ) : (
                      <Badge variant="default">Unavailable</Badge>
                    )}
                  </div>
                </div>
                <div>
                  <p className="text-xs text-bne-steel mb-1">Risk Score</p>
                  {typeof selectedConnection.riskScore === 'number' ? (
                    <div className="flex items-center gap-2">
                      <div className="flex-1 bg-bne-frost rounded-full h-2 overflow-hidden">
                        <div
                          className="h-full rounded-full transition-all"
                          style={{
                            width: `${selectedConnection.riskScore * 100}%`,
                            backgroundColor: getRiskColor(selectedConnection.riskScore)
                          }}
                        />
                      </div>
                      <span className="text-xs font-mono font-semibold text-bne-ink">
                        {(selectedConnection.riskScore * 100).toFixed(1)}%
                      </span>
                    </div>
                  ) : (
                    <p className="text-sm text-bne-steel">
                      Not reported for this exposure. A risk score is never inferred
                      from an exposure amount.
                    </p>
                  )}
                </div>
                <div>
                  <p className="text-xs text-bne-steel mb-1">Transaction Volume</p>
                  <p className="font-medium text-bne-ink">
                    {typeof selectedConnection.transactionVolume === 'number'
                      ? `${selectedConnection.transactionVolume.toLocaleString()} transactions`
                      : 'Unavailable'}
                  </p>
                </div>
                {selectedConnection.layer && (
                  <div>
                    <p className="text-xs text-bne-steel mb-1">Layer</p>
                    <p className="font-medium text-bne-ink">
                      {selectedConnection.layer}
                      {selectedConnection.kind ? ` (${selectedConnection.kind})` : ''}
                    </p>
                  </div>
                )}
              </div>
              <div className="mt-4 pt-4 border-t border-bne-frost">
                <Button variant="outline" size="sm" className="w-full">
                  View Detailed Analysis
                </Button>
              </div>
            </Card>
          )}

          {selectedRegion && !selectedConnection && (
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
                            <th className="px-3 py-2 text-left">Risk</th>
                          </tr>
                        </thead>
                        <tbody>
                          {banks.map((bank) => (
                            <tr key={bank.id} className="border-t border-bne-frost">
                              <td className="px-3 py-2 font-mono text-xs text-bne-ink">{bank.code}</td>
                              <td className="px-3 py-2 text-bne-ink">{bank.name}</td>
                              <td className="px-3 py-2 text-xs font-mono text-bne-steel">
                                {typeof bank.risk_score === 'number' ? bank.risk_score.toFixed(2) : '—'}
                              </td>
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

          {!selectedRegion && !selectedConnection && (
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
                <p className="text-sm text-bne-steel mb-2">
                  Select a region from the map or the region list to view details
                </p>
                {showNetwork && (
                  <p className="text-xs text-bne-steel">
                    Or click on an exposure arc to see connection info
                  </p>
                )}
              </div>
            </Card>
          )}

          <Card>
            <h3 className="font-semibold text-bne-ink mb-4">Exposure Summary</h3>
            {fallbackActive && (
              <p className="mb-3 rounded-lg bg-amber-100 px-3 py-2 text-xs text-amber-900">
                DEMO NETWORK — backend unavailable; these totals come from the bundled
                sample file, not from live exposures.
              </p>
            )}
            <div className="space-y-3">
              <div className="flex items-center justify-between">
                <span className="text-sm text-bne-steel">Total Network Exposure</span>
                <span className="text-sm font-semibold text-bne-ink">
                  {networkSummary.count > 0 ? formatExposure(networkSummary.totalExposure) : 'Unavailable'}
                </span>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-sm text-bne-steel">Average Corridor Risk</span>
                {networkSummary.averageRisk != null ? (
                  <Badge
                    variant={
                      networkSummary.averageRisk < 0.3
                        ? 'success'
                        : networkSummary.averageRisk < 0.6
                        ? 'default'
                        : 'warning'
                    }
                    size="sm"
                  >
                    {(networkSummary.averageRisk * 100).toFixed(1)}%
                  </Badge>
                ) : (
                  <Badge variant="default" size="sm">Unavailable</Badge>
                )}
              </div>
              <div className="flex items-center justify-between">
                <span className="text-sm text-bne-steel">Highest Risk Corridor</span>
                <span className="text-xs font-medium text-bne-ink">
                  {networkSummary.riskiest
                    ? `${getRegionName(networkSummary.riskiest.source)} → ${getRegionName(networkSummary.riskiest.target)}`
                    : 'Unavailable'}
                </span>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-sm text-bne-steel">Largest Exposure Corridor</span>
                <span className="text-xs font-medium text-bne-ink">
                  {networkSummary.largest
                    ? `${getRegionName(networkSummary.largest.source)} → ${getRegionName(networkSummary.largest.target)}`
                    : 'Unavailable'}
                </span>
              </div>
            </div>
          </Card>

          <Card>
            <h3 className="font-semibold text-bne-ink mb-4">Quick Stats</h3>
            <div className="space-y-3">
              <div className="flex items-center justify-between">
                <span className="text-sm text-bne-steel">Total Regions</span>
                <Badge variant="info" size="sm">{regions.length}</Badge>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-sm text-bne-steel">Total Banks</span>
                <Badge variant="primary" size="sm">
                  {regions.reduce((sum, region) => sum + region.bankCount, 0).toLocaleString()}
                </Badge>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-sm text-bne-steel">Interbank Corridors</span>
                <Badge variant="success" size="sm">{networkSummary.count}</Badge>
              </div>
            </div>
          </Card>
        </div>
      </div>
    </PageContainer>
  )
}

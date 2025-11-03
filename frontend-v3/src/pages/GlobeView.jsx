import { useState } from 'react'
import { useStore } from '../store/useStore'
import PageContainer from '../components/ui/PageContainer'
import Card from '../components/ui/Card'
import Button from '../components/ui/Button'
import Badge from '../components/ui/Badge'
import GlobeCanvas from '../components/globe/GlobeCanvas'

export default function GlobeView() {
  const { selectedRegion, setSelectedRegion, globeRotation, setGlobeRotation } = useStore()
  const [selectedDataSource, setSelectedDataSource] = useState('fdic')

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
              <div className="mt-4 pt-4 border-t border-bne-frost">
                <Button variant="primary" size="sm" className="w-full">
                  View Bank Data
                </Button>
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

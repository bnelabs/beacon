import { useMemo } from 'react'
import { useUIStore } from '../state/uiStore.js'
import { REGION_LOOKUP } from '../config/regions.js'

export function RegionDetails() {
  const selected = useUIStore((state) => state.selectedRegions)
  const dataJobId = useUIStore((state) => state.dataJobId)
  const trainingJobId = useUIStore((state) => state.trainingJobId)
  const selectedCountries = useUIStore((state) => state.selectedCountries)
  const confirmedCountries = useUIStore((state) => state.confirmedCountries)

  const region = useMemo(() => {
    if (selected.length === 0) return null
    return REGION_LOOKUP[selected[selected.length - 1]] ?? null
  }, [selected])

  if (!region) {
    return (
      <div className="rounded-3xl border border-dashed border-bne-silver/60 bg-white/60 p-5 text-sm text-bne-steel/80">
        <p className="font-medium text-bne-steel">
          Awaiting region selection
        </p>
        <p className="mt-2 leading-relaxed">
          Tap highlighted continents on the globe to unlock granular liquidity views and curated data catalogues.
        </p>
      </div>
    )
  }

  const activeCountries = useMemo(() => {
    if (confirmedCountries.length > 0) {
      return confirmedCountries
    }
    return selectedCountries
  }, [confirmedCountries, selectedCountries])

  const dataStatusMessage = useMemo(() => {
    if (activeCountries.length > 0) {
      if (confirmedCountries.length > 0) {
        return `Last data pipeline completed for ${confirmedCountries.join(', ')}. Subsequent stages will use this confirmed scope.`
      }
      return `Country drill-down activated for ${activeCountries.join(', ')}. Run the data pipeline to surface per-country risk metrics.`
    }
    if (!dataJobId) {
      return 'Trigger a data download for this region to collect live metrics.'
    }
    if (!trainingJobId) {
      return 'Data collected. Launch model training to compute liquidity analytics for this region.'
    }
    return 'Latest liquidity metrics will stream in from the completed models once the prediction pipeline finishes.'
  }, [dataJobId, trainingJobId, activeCountries, confirmedCountries])

  return (
    <div className="space-y-4 rounded-3xl bg-white/70 p-6 shadow-bne-panel">
      <div>
        <p className="text-xs font-semibold uppercase tracking-[0.3em] text-bne-azure">Region Focus</p>
        <h3 className="mt-2 text-lg font-semibold text-bne-ink">{region.name}</h3>
      </div>

      <div className="rounded-2xl bg-bne-ice/80 p-4 text-sm text-bne-steel/80">
        {dataStatusMessage}
      </div>
    </div>
  )
}

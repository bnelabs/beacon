import { useUIStore } from '../state/uiStore.js'
import { REGION_LOOKUP } from '../config/regions.js'

export function RegionBadgeList() {
  const selected = useUIStore((state) => state.selectedRegions)

  if (selected.length === 0) {
    return null
  }

  return (
    <div className="flex flex-wrap justify-center gap-2 sm:justify-start">
      {selected.map((code) => {
        const meta = REGION_LOOKUP[code] ?? { name: code, gradient: 'from-bne-ink to-bne-steel' }
        return (
          <div
            key={code}
            className={`rounded-full bg-gradient-to-r ${meta.gradient} px-4 py-1.5 text-xs font-semibold text-white shadow-sm`}
          >
            {meta.name}
          </div>
        )
      })}
    </div>
  )
}

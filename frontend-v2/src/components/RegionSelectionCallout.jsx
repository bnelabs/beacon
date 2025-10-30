import { motion } from 'framer-motion'
import { useUIStore } from '../state/uiStore.js'

export function RegionSelectionCallout() {
  const selected = useUIStore((state) => state.selectedRegions)
  const globeReady = useUIStore((state) => state.globeReady)

  if (!globeReady) {
    return null
  }

  const message =
    selected.length === 0
      ? 'Orbit the globe and select one or more macro regions to initialise the data pipeline.'
      : 'Click individual countries within the highlighted region to drill into bank-level configuration.'

  return (
    <motion.div
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: 0.5, duration: 0.6 }}
      className="pointer-events-none absolute left-8 top-8 max-w-sm rounded-3xl bg-white/80 p-5 text-sm text-bne-steel shadow-lg backdrop-blur-lg"
    >
      <p className="text-xs font-semibold uppercase tracking-[0.32em] text-bne-azure">
        Interaction Guide
      </p>
      <p className="mt-2 leading-relaxed">{message}</p>
    </motion.div>
  )
}

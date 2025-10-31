import { useMemo } from 'react'
import { Shell } from './components/Layout.jsx'
import { GlobeCanvas } from './components/GlobeCanvas.jsx'
import { useUIStore } from './state/uiStore.js'
import { motion } from 'framer-motion'
import { RegionBadgeList } from './components/RegionBadgeList.jsx'
import { RegionDetails } from './components/RegionDetails.jsx'
import { RegionSelectionCallout } from './components/RegionSelectionCallout.jsx'
import { RegionDataPanel } from './components/RegionDataPanel.jsx'

const BRAND_NAME = 'BEACON'

function Header() {
  return (
    <div className="flex w-full flex-col gap-5 sm:flex-row sm:items-center sm:justify-between">
      <div className="flex flex-col items-center gap-4 sm:flex-row sm:items-center">
        <div className="flex h-12 w-12 items-center justify-center rounded-full bg-bne-azure/10 text-bne-azure">
          <svg width="28" height="28" viewBox="0 0 32 32" fill="none">
            <circle cx="16" cy="16" r="14" stroke="currentColor" strokeWidth="2.2" />
            <path
              d="M8.5 21.2C10.7 17.5 13.4 15.6 16 15.6C18.6 15.6 21.3 17.5 23.5 21.2"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinecap="round"
            />
            <path
              d="M13.2 9.5C14.2 11.4 15.1 12.2 16 12.2C16.9 12.2 17.8 11.4 18.8 9.5"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinecap="round"
            />
          </svg>
        </div>
        <div className="text-center sm:text-left">
          <p className="text-[11px] font-medium uppercase tracking-[0.24em] text-bne-steel">
            Banking Network Engine
          </p>
          <h1 className="text-2xl font-semibold tracking-tight text-bne-ink sm:text-3xl">
            {BRAND_NAME}
          </h1>
        </div>
      </div>

      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:gap-6">
        <div className="flex items-center justify-center gap-3 rounded-full bg-white/70 px-5 py-2 text-center shadow-bne-panel">
          <div className="h-2 w-2 rounded-full bg-bne-emerald" />
          <span className="text-sm font-medium text-bne-steel">Systems Operational</span>
        </div>
        <button className="w-full rounded-full border border-white/60 bg-white/80 px-5 py-2 text-sm font-medium text-bne-steel transition hover:border-bne-azure/40 hover:text-bne-azure sm:w-auto">
          User Console
        </button>
      </div>
    </div>
  )
}

function PlaceholderSidebar() {
  const selectedRegions = useUIStore((state) => state.selectedRegions)
  const globeReady = useUIStore((state) => state.globeReady)

  const statusMessage = useMemo(() => {
    if (!globeReady) {
      return 'Initializing geospatial layers...'
    }
    if (selectedRegions.length === 0) {
      return 'Select a region to begin configuring data sources.'
    }
    return `Regions selected: ${selectedRegions.join(', ')}`
  }, [globeReady, selectedRegions])

  return (
    <div className="flex h-full flex-col gap-6">
      <div className="text-center sm:text-left">
        <p className="text-xs uppercase tracking-[0.32em] text-bne-azure">Navigator</p>
        <h2 className="mt-2 text-xl font-semibold text-bne-ink sm:text-2xl">
          Region Intelligence Console
        </h2>
      </div>
      <div className="space-y-4 text-sm text-bne-steel">
        <p className="text-center leading-relaxed sm:text-left">
          The interactive globe provides a macro liquidity overview. Click or drag to explore
          BEACON&apos;s multi-region sensing mesh.
        </p>
        <div className="rounded-2xl border border-bne-silver/50 bg-bne-ice/60 p-4 shadow-inner">
          <p className="text-xs font-semibold uppercase tracking-[0.18em] text-bne-steel/70">
            Status
          </p>
          <p className="mt-2 text-sm font-medium text-bne-ink">{statusMessage}</p>
        </div>
      </div>
      <RegionBadgeList />
      <RegionDetails />
      <div className="mt-auto space-y-3 text-xs text-bne-steel/70">
        <p>• Globe auto-rotation can be paused with drag interaction.</p>
        <p>• Zoom and detailed region overlays unlock after your initial selection.</p>
      </div>
    </div>
  )
}

function GlobePanel() {
  return (
    <div className="relative min-h-[360px] overflow-hidden rounded-3xl bg-gradient-to-br from-[#03050a] via-[#060912] to-[#010204] sm:min-h-[420px] lg:h-[600px]">
      <motion.div
        className="absolute inset-0"
        initial={{ opacity: 0 }}
        animate={{ opacity: 0.85 }}
        transition={{ delay: 0.2, duration: 0.8 }}
      >
        <GlobeCanvas />
      </motion.div>
      <div className="pointer-events-none absolute inset-x-4 bottom-6 flex justify-center sm:inset-x-8 sm:bottom-8 lg:inset-x-10 lg:bottom-10">
        <div className="rounded-full border border-white/20 bg-white/10 px-5 py-2.5 text-xs font-medium uppercase tracking-[0.24em] text-white/80 shadow-lg backdrop-blur-lg sm:px-6 sm:py-3 sm:text-sm sm:tracking-[0.3em]">
          Global Liquidity Network
        </div>
      </div>
      <RegionSelectionCallout />
    </div>
  )
}

export default function App() {
  const selectedRegions = useUIStore((state) => state.selectedRegions)
  const sidebarContent = selectedRegions.length > 0 ? <RegionDataPanel /> : <PlaceholderSidebar />

  return (
    <Shell header={<Header />} sidebar={sidebarContent}>
      <GlobePanel />
    </Shell>
  )
}

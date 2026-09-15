import { create } from 'zustand'

/**
 * A scored geographic region: the selection unit shared across the dashboard
 * and the risk map. Mirrors the static reference table in
 * `src/data/regions.js`. Typed here so every consumer of the store gets a
 * strict contract for this analytical payload instead of an `any` blob —
 * this is the kind of complex shared state the TypeScript migration is meant
 * to pin down.
 */
export interface Region {
  id: string
  name: string
  country: string
  iso3: string
  lat: number
  lon: number
  color: string
  bankCount: number
}

/** Identifier of a configured data source (e.g. `'fdic'`, `'fred'`). */
export type DataSourceId = string

export interface StoreState {
  selectedRegion: Region | null
  setSelectedRegion: (region: Region | null) => void

  selectedDataSource: DataSourceId
  setSelectedDataSource: (source: DataSourceId) => void

  sidebarOpen: boolean
  setSidebarOpen: (open: boolean) => void
  toggleSidebar: () => void
}

export const useStore = create<StoreState>()((set) => ({
  selectedRegion: null,
  setSelectedRegion: (region) => set({ selectedRegion: region }),

  selectedDataSource: 'fdic',
  setSelectedDataSource: (source) => set({ selectedDataSource: source }),

  sidebarOpen: true,
  setSidebarOpen: (open) => set({ sidebarOpen: open }),
  toggleSidebar: () => set((state) => ({ sidebarOpen: !state.sidebarOpen }))
}))

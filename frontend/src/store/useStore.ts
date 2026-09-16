import { create } from 'zustand'
import type { Region } from '../data/regions'

// The canonical `Region` shape lives with the region reference data
// (`data/regions.ts`). Re-exported here so existing
// `import { type Region } from '.../store/useStore'` keeps working.
export type { Region }

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

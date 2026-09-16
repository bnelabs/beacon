import { create } from 'zustand'
import type { Region } from '../data/regions'

// The canonical `Region` shape lives with the region reference data
// (`data/regions.ts`); import it from there. A compat re-export used to live
// here "so existing imports keep working" — none did (the reachability check
// in scripts/check_frontend_hook_reachability.mjs covers stores too).

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

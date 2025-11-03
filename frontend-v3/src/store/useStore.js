import { create } from 'zustand'

export const useStore = create((set) => ({
  selectedRegion: null,
  setSelectedRegion: (region) => set({ selectedRegion: region }),

  selectedDataSource: 'fdic',
  setSelectedDataSource: (source) => set({ selectedDataSource: source }),

  globeRotation: true,
  setGlobeRotation: (enabled) => set({ globeRotation: enabled }),

  sidebarOpen: true,
  setSidebarOpen: (open) => set({ sidebarOpen: open }),
  toggleSidebar: () => set((state) => ({ sidebarOpen: !state.sidebarOpen }))
}))

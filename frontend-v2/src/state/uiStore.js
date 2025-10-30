import { create } from 'zustand'

export const useUIStore = create((set) => ({
  selectedRegions: [],
  setSelectedRegions: (regions) => set({ selectedRegions: regions }),
  toggleRegion: (code) =>
    set((state) => {
      const selected = state.selectedRegions.includes(code)
      return {
        selectedRegions: selected
          ? state.selectedRegions.filter((r) => r !== code)
          : [...state.selectedRegions, code]
      }
    }),
  clearRegions: () => set({ selectedRegions: [], selectedCountries: [], focusedRegion: null, focusedCountry: null }),
  focusedRegion: null,
  setFocusedRegion: (region) => set({ focusedRegion: region }),
  selectedCountries: [],
  toggleCountry: (country) =>
    set((state) => {
      const exists = state.selectedCountries.includes(country)
      return {
        selectedCountries: exists
          ? state.selectedCountries.filter((c) => c !== country)
          : [...state.selectedCountries, country]
      }
    }),
  clearCountries: () => set({ selectedCountries: [] }),
  removeCountries: (countries) =>
    set((state) => ({
      selectedCountries: state.selectedCountries.filter((c) => !countries.includes(c))
    })),
  focusedCountry: null,
  setFocusedCountry: (country) => set({ focusedCountry: country }),
  panelStage: 'sources',
  setPanelStage: (stage) => set({ panelStage: stage }),
  selectedSourceIds: [],
  toggleSource: (id) =>
    set((state) => {
      const exists = state.selectedSourceIds.includes(id)
      return {
        selectedSourceIds: exists
          ? state.selectedSourceIds.filter((sid) => sid !== id)
          : [...state.selectedSourceIds, id]
      }
    }),
  resetSources: () => set({ selectedSourceIds: [], panelStage: 'sources' }),
  selectedAssetIds: [],
  toggleAsset: (id) =>
    set((state) => {
      const exists = state.selectedAssetIds.includes(id)
      return {
        selectedAssetIds: exists
          ? state.selectedAssetIds.filter((aid) => aid !== id)
          : [...state.selectedAssetIds, id]
      }
    }),
  resetAssets: () => set({ selectedAssetIds: [] }),
  dataJobId: null,
  setDataJobId: (jobId) => set({ dataJobId: jobId }),
  trainingJobId: null,
  setTrainingJobId: (jobId) => set({ trainingJobId: jobId }),
  selectedModelId: null,
  setSelectedModelId: (modelId) => set({ selectedModelId: modelId }),
  confirmedRegions: [],
  confirmedCountries: [],
  setConfirmedScope: (regions, countries) =>
    set({
      confirmedRegions: Array.isArray(regions) ? regions.filter(Boolean) : [],
      confirmedCountries: Array.isArray(countries) ? countries.filter(Boolean) : [],
    }),
  predictionJobId: null,
  setPredictionJobId: (jobId) => set({ predictionJobId: jobId }),
  backtestJobId: null,
  setBacktestJobId: (jobId) => set({ backtestJobId: jobId }),
  resetWorkflow: () =>
    set({
      panelStage: 'sources',
      selectedSourceIds: [],
      selectedAssetIds: [],
      dataJobId: null,
      trainingJobId: null,
      selectedModelId: null,
      predictionJobId: null,
      backtestJobId: null,
      focusedRegion: null,
      selectedCountries: [],
      focusedCountry: null,
      confirmedRegions: [],
      confirmedCountries: [],
    }),
  sidebarOpen: false,
  setSidebarOpen: (open) => set({ sidebarOpen: open }),
  globeReady: false,
  setGlobeReady: (ready) => set({ globeReady: ready })
}))

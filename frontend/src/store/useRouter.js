import { create } from 'zustand'

export const useRouter = create((set) => ({
  currentPage: 'dashboard',
  params: {},
  navigate: (page, params = {}) => set({ currentPage: page, params })
}))

import { create } from 'zustand'

export const useRouter = create((set) => ({
  currentPage: 'dashboard',
  navigate: (page) => set({ currentPage: page })
}))

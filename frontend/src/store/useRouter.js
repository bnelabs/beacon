import { create } from 'zustand'

/**
 * Navigation store with hash-routed deep links (P4).
 *
 * The store-only router lost every deep link on reload: the app always
 * reopened on the dashboard, so a shared validation report or job view was
 * unshareable. Page and params now live in the location hash
 * (`#/results?jobId=4`): reloads, bookmarks and shared URLs survive, with no
 * router library and no server-side rewrite requirements (the SPA is served
 * statically by nginx).
 */
function parseHash() {
  const raw = (typeof window === 'undefined' ? '' : window.location.hash).replace(/^#\/?/, '')
  if (!raw) return { currentPage: 'dashboard', params: {} }
  const [path, query = ''] = raw.split('?')
  const params = {}
  for (const [key, value] of new URLSearchParams(query)) {
    params[key] = value
  }
  return { currentPage: path || 'dashboard', params }
}

function writeHash(page, params) {
  const query = new URLSearchParams(params || {}).toString()
  const next = `#/${page}${query ? `?${query}` : ''}`
  if (window.location.hash !== next) {
    window.location.hash = next
  }
}

const initial = parseHash()

export const useRouter = create((set) => ({
  currentPage: initial.currentPage,
  params: initial.params,
  navigate: (page, params = {}) => {
    writeHash(page, params)
    set({ currentPage: page, params })
  }
}))

if (typeof window !== 'undefined') {
  const sync = () => {
    const { currentPage, params } = parseHash()
    useRouter.setState({ currentPage, params })
  }
  window.addEventListener('hashchange', sync)
  window.addEventListener('popstate', sync)
}

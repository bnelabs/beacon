import { useRouter } from '../store/useRouter'

const PAGE_METADATA = {
  dashboard: { title: 'Dashboard', parent: null },
  globe: { title: 'Globe View', parent: null },
  models: { title: 'Models', parent: null },
  jobs: { title: 'Jobs', parent: null },
  datasources: { title: 'Data Sources', parent: null },
  countries: { title: 'Country Profiles', parent: null },
  results: { title: 'Results', parent: 'jobs' },
  settings: { title: 'Settings', parent: null },
  help: { title: 'Help Center', parent: null }
}

export default function Breadcrumbs() {
  const { currentPage, params, navigate } = useRouter()

  // Build breadcrumb trail
  const buildBreadcrumbs = () => {
    const crumbs = []
    let page = currentPage

    // Always start with home
    crumbs.unshift({
      title: 'Home',
      page: 'dashboard',
      isLast: false
    })

    // Build chain from current page to root
    while (page && PAGE_METADATA[page]) {
      const metadata = PAGE_METADATA[page]

      crumbs.push({
        title: metadata.title,
        page: page,
        isLast: true
      })

      // Check if there's a parent
      if (metadata.parent) {
        page = metadata.parent
      } else {
        break
      }
    }

    // Mark last item
    if (crumbs.length > 0) {
      crumbs[crumbs.length - 1].isLast = true
      // Unmark previous last items
      for (let i = 0; i < crumbs.length - 1; i++) {
        crumbs[i].isLast = false
      }
    }

    // Add dynamic segments (like job ID, model name, etc)
    if (params?.jobId) {
      crumbs.push({
        title: `Job #${params.jobId}`,
        page: currentPage,
        isLast: true
      })
      crumbs[crumbs.length - 2].isLast = false
    }

    if (params?.modelId) {
      crumbs.push({
        title: `Model #${params.modelId}`,
        page: currentPage,
        isLast: true
      })
      crumbs[crumbs.length - 2].isLast = false
    }

    return crumbs
  }

  const breadcrumbs = buildBreadcrumbs()

  // Don't show breadcrumbs if only one item (home == current page)
  if (breadcrumbs.length <= 1) {
    return null
  }

  return (
    <nav aria-label="Breadcrumb" className="flex items-center space-x-2 text-sm">
      {breadcrumbs.map((crumb, index) => (
        <div key={`${crumb.page}-${index}`} className="flex items-center">
          {index > 0 && (
            <svg
              className="w-4 h-4 mx-2 text-bne-steel/50"
              fill="none"
              viewBox="0 0 24 24"
              stroke="currentColor"
              strokeWidth={2}
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                d="M9 5l7 7-7 7"
              />
            </svg>
          )}

          {crumb.isLast ? (
            <span className="text-bne-ink font-medium" aria-current="page">
              {crumb.title}
            </span>
          ) : (
            <button
              onClick={() => navigate(crumb.page)}
              className="text-bne-steel hover:text-bne-ink transition-colors"
              type="button"
            >
              {crumb.title}
            </button>
          )}
        </div>
      ))}
    </nav>
  )
}

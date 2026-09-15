import { useState, useEffect, useMemo, useRef } from 'react'
import { API_ORIGIN, asList, fetchJson } from '../utils/apiClient'
import { useRouter } from '../store/useRouter'
import { useQuery } from '@tanstack/react-query'
import Card from './ui/Card'
import Badge from './ui/Badge'
import LoadingSpinner from './ui/LoadingSpinner'

// Same-origin by default; nginx proxies /api/ to the backend. See the note in
// hooks/useCountries.js for why localhost:3456 is the wrong default here.
// Fetch and refuse a non-2xx response. Previously the queries returned
// res.json() unconditionally, so a 404 yielded {"detail": "Not Found"} and the
// category silently came back empty — which is how a wrong URL went unnoticed.
// Fuzzy match scoring
function fuzzyMatch(str, pattern) {
  const patternLower = pattern.toLowerCase()
  const strLower = str.toLowerCase()

  let patternIdx = 0
  let score = 0
  let consecutiveBonus = 0

  for (let i = 0; i < strLower.length; i++) {
    if (strLower[i] === patternLower[patternIdx]) {
      score += 1 + consecutiveBonus
      consecutiveBonus += 5
      patternIdx++

      if (patternIdx === patternLower.length) {
        return score
      }
    } else {
      consecutiveBonus = 0
    }
  }

  return patternIdx === patternLower.length ? score : 0
}

export default function GlobalSearch() {
  const [isOpen, setIsOpen] = useState(false)
  const [query, setQuery] = useState('')
  const [selectedIndex, setSelectedIndex] = useState(0)
  const inputRef = useRef(null)
  const { navigate } = useRouter()

  // Fetch searchable data. Each query is independent, so a category whose
  // endpoint is unavailable degrades on its own rather than emptying the palette.
  // URLs match the existing hooks in useApi.js: a trailing slash is not required
  // by any of them, and /api/models is the path the rest of the app uses for the
  // model catalogue (the backend mounts it at both /api/models and /api/v1/models).
  const { data: jobsData } = useQuery({
    queryKey: ['jobs'],
    queryFn: () => fetchJson(`${API_ORIGIN}/api/v1/jobs`),
    enabled: isOpen,
    staleTime: 30000
  })

  const { data: modelsData } = useQuery({
    queryKey: ['models'],
    queryFn: () => fetchJson(`${API_ORIGIN}/api/models`),
    enabled: isOpen,
    staleTime: 60000
  })

  // Was /api/v1/data-catalogue/, which does not exist. The catalogue route is
  // /api/v1/catalogue (see docs/api-endpoints.md).
  const { data: catalogueData } = useQuery({
    queryKey: ['catalogue'],
    queryFn: () => fetchJson(`${API_ORIGIN}/api/v1/catalogue`),
    enabled: isOpen,
    staleTime: 60000
  })

  const { data: countriesData } = useQuery({
    queryKey: ['countries-search'],
    queryFn: () => fetchJson(`${API_ORIGIN}/api/v1/countries/`),
    enabled: isOpen,
    staleTime: 60000
  })

  // Build searchable items
  const searchableItems = useMemo(() => {
    const items = []

    // Static pages
    items.push(
      { id: 'dashboard', title: 'Dashboard', category: 'Page', page: 'dashboard', icon: 'DA' },
      { id: 'globe', title: 'Risk Map', category: 'Page', page: 'globe', icon: 'RM' },
      { id: 'models', title: 'Models', category: 'Page', page: 'models', icon: 'MD' },
      { id: 'jobs', title: 'Jobs', category: 'Page', page: 'jobs', icon: 'JB' },
      { id: 'datasources', title: 'Data Sources', category: 'Page', page: 'datasources', icon: 'DS' },
      { id: 'countries', title: 'Country Profiles', category: 'Page', page: 'countries', icon: 'CP' },
      { id: 'results', title: 'Results', category: 'Page', page: 'results', icon: 'RS' },
      { id: 'settings', title: 'Settings', category: 'Page', page: 'settings', icon: 'ST' }
    )

    // Jobs — GET /api/v1/jobs answers with a bare array of JobResponse.
    asList(jobsData, 'jobs').forEach(job => {
      items.push({
        id: `job-${job.id}`,
        title: `Job #${job.id} - ${job.job_type}`,
        subtitle: job.status,
        category: 'Job',
        page: 'jobs',
        icon: 'JB',
        meta: `${Math.round(job.progress ?? 0)}%`
      })
    })

    // Models — ModelSummary exposes model_id / name / model_version. The previous
    // code read id / model_name / version, none of which exist on that schema.
    asList(modelsData, 'models').forEach(model => {
      items.push({
        id: `model-${model.model_id}`,
        title: model.name,
        subtitle: model.model_type,
        category: 'Model',
        page: 'models',
        icon: 'MD',
        meta: model.model_version
      })
    })

    // Catalogue — DataCatalogueItemResponse; the source is a nested object, and
    // there is no `series_id` field on it.
    asList(catalogueData, 'items').forEach(item => {
      items.push({
        id: `catalogue-${item.id}`,
        title: item.name,
        subtitle: item.description,
        category: 'Data Catalogue',
        page: 'datasources',
        icon: 'DS',
        meta: item.data_source?.name
      })
    })

    // Countries — CountryListResponse is a wrapper object, so this one needs the key.
    asList(countriesData, 'countries').forEach(country => {
      items.push({
        id: `country-${country.id}`,
        title: country.country_name,
        subtitle: country.region,
        category: 'Country',
        page: 'countries',
        icon: 'CP',
        meta: country.country_code
      })
    })

    return items
  }, [jobsData, modelsData, catalogueData, countriesData])

  // Filter and rank results
  const results = useMemo(() => {
    if (!query.trim()) return searchableItems.slice(0, 15)

    const scored = searchableItems
      .map(item => {
        const titleScore = fuzzyMatch(item.title, query)
        const subtitleScore = item.subtitle ? fuzzyMatch(item.subtitle, query) * 0.5 : 0
        const categoryScore = fuzzyMatch(item.category, query) * 0.3
        const score = titleScore + subtitleScore + categoryScore
        return { ...item, score }
      })
      .filter(item => item.score > 0)
      .sort((a, b) => b.score - a.score)
      .slice(0, 10)

    return scored
  }, [query, searchableItems])

  // Keyboard shortcuts
  useEffect(() => {
    const handleKeyDown = (e) => {
      // Cmd+K or Ctrl+K to open
      if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
        e.preventDefault()
        setIsOpen(prev => !prev)
        setQuery('')
        setSelectedIndex(0)
      }

      // Escape to close
      if (e.key === 'Escape' && isOpen) {
        setIsOpen(false)
        setQuery('')
      }

      // Arrow keys navigation
      if (isOpen && results.length > 0) {
        if (e.key === 'ArrowDown') {
          e.preventDefault()
          setSelectedIndex(prev => (prev + 1) % results.length)
        } else if (e.key === 'ArrowUp') {
          e.preventDefault()
          setSelectedIndex(prev => (prev - 1 + results.length) % results.length)
        } else if (e.key === 'Enter') {
          e.preventDefault()
          const selected = results[selectedIndex]
          if (selected) {
            navigate(selected.page)
            setIsOpen(false)
            setQuery('')
          }
        }
      }
    }

    document.addEventListener('keydown', handleKeyDown)
    return () => document.removeEventListener('keydown', handleKeyDown)
  }, [isOpen, results, selectedIndex, navigate])

  // Focus input when opened
  useEffect(() => {
    if (isOpen && inputRef.current) {
      inputRef.current.focus()
    }
  }, [isOpen])

  if (!isOpen) return null

  return (
    <div
      className="fixed inset-0 bg-bne-ink/40 z-50 flex items-start justify-center pt-[15vh]"
      onClick={() => setIsOpen(false)}
    >
      <div
        className="w-full max-w-2xl mx-4"
        onClick={(e) => e.stopPropagation()}
      >
        <Card className="overflow-hidden shadow-2xl">
          {/* Search Input */}
          <div className="flex items-center gap-3 px-4 py-3 border-b border-bne-line">
            <svg
              className="w-5 h-5 text-bne-muted"
              fill="none"
              viewBox="0 0 24 24"
              stroke="currentColor"
              strokeWidth={2}
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z"
              />
            </svg>
            <input
              ref={inputRef}
              type="text"
              placeholder="Search pages, jobs, models, countries..."
              value={query}
              onChange={(e) => {
                setQuery(e.target.value)
                setSelectedIndex(0)
              }}
              className="flex-1 text-base text-bne-ink placeholder-bne-muted bg-transparent border-none outline-none"
            />
            <kbd className="hidden sm:inline-block px-2 py-1 text-xs font-mono text-bne-muted bg-bne-paper rounded border border-bne-line">
              ESC
            </kbd>
          </div>

          {/* Results */}
          <div className="max-h-[60vh] overflow-y-auto">
            {results.length === 0 ? (
              <div className="py-12 text-center">
                {query ? (
                  <>
                    <svg
                      className="w-12 h-12 mx-auto text-bne-muted/30 mb-3"
                      fill="none"
                      viewBox="0 0 24 24"
                      stroke="currentColor"
                    >
                      <path
                        strokeLinecap="round"
                        strokeLinejoin="round"
                        strokeWidth={2}
                        d="M9.172 16.172a4 4 0 015.656 0M9 10h.01M15 10h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"
                      />
                    </svg>
                    <p className="text-sm text-bne-muted">No results found for "{query}"</p>
                  </>
                ) : (
                  <LoadingSpinner message="Loading search index..." />
                )}
              </div>
            ) : (
              <div className="py-2">
                {results.map((item, index) => (
                  <button
                    key={item.id}
                    onClick={() => {
                      navigate(item.page)
                      setIsOpen(false)
                      setQuery('')
                    }}
                    onMouseEnter={() => setSelectedIndex(index)}
                    className={`w-full flex items-center gap-3 px-4 py-3 text-left transition-colors ${
                      index === selectedIndex
                        ? 'bg-bne-pine/10 border-l-2 border-bne-pine'
                        : 'hover:bg-bne-paper/50'
                    }`}
                  >
                    <span className="w-9 h-9 shrink-0 rounded-md border border-bne-line bg-bne-paper-raise flex items-center justify-center font-display text-[12px] font-semibold tracking-wide text-bne-muted">{item.icon}</span>
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2">
                        <p className="text-sm font-medium text-bne-ink truncate">
                          {item.title}
                        </p>
                        {item.meta && (
                          <span className="text-xs font-mono text-bne-muted">
                            {item.meta}
                          </span>
                        )}
                      </div>
                      {item.subtitle && (
                        <p className="text-xs text-bne-muted truncate mt-0.5">
                          {item.subtitle}
                        </p>
                      )}
                    </div>
                    <Badge variant="default" size="sm">
                      {item.category}
                    </Badge>
                  </button>
                ))}
              </div>
            )}
          </div>

          {/* Footer */}
          <div className="flex items-center justify-between px-4 py-2 border-t border-bne-line bg-bne-paper/30 text-xs text-bne-muted">
            <div className="flex items-center gap-4">
              <span className="flex items-center gap-1">
                <kbd className="px-1.5 py-0.5 font-mono bg-bne-card rounded border border-bne-line">↑</kbd>
                <kbd className="px-1.5 py-0.5 font-mono bg-bne-card rounded border border-bne-line">↓</kbd>
                <span>Navigate</span>
              </span>
              <span className="flex items-center gap-1">
                <kbd className="px-1.5 py-0.5 font-mono bg-bne-card rounded border border-bne-line">↵</kbd>
                <span>Select</span>
              </span>
            </div>
            <span className="flex items-center gap-1">
              <kbd className="px-1.5 py-0.5 font-mono bg-bne-card rounded border border-bne-line">⌘K</kbd>
              <span>Toggle</span>
            </span>
          </div>
        </Card>
      </div>
    </div>
  )
}

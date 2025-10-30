export const API_BASE = typeof __API_BASE_URL__ !== 'undefined' ? __API_BASE_URL__ : import.meta.env.VITE_API_BASE_URL

async function handleResponse(response) {
  if (!response.ok) {
    const detail = await response.json().catch(() => ({}))
    const technical = detail?.detail?.technical ?? response.statusText
    const userFriendly = detail?.detail?.user_friendly ?? 'An unexpected error occurred while reaching BEACON services.'
    const error = new Error(userFriendly)
    error.technical = technical
    error.status = response.status
    throw error
  }
  return response.json()
}

export async function fetchDatasources({ regions }) {
  const params = new URLSearchParams()
  if (regions?.length) {
    params.set('regions', regions.join(','))
  }
  const url = `${API_BASE}/api/v2/datasources?${params.toString()}`
  const response = await fetch(url, { credentials: 'include' })
  return handleResponse(response)
}

export async function fetchCatalogue({ sourceIds, page = 1, pageSize = 25, search }) {
  const params = new URLSearchParams({ page: String(page), page_size: String(pageSize) })
  if (sourceIds?.length) {
    params.set('sources', sourceIds.join(','))
  }
  if (search) {
    params.set('search', search)
  }
  const url = `${API_BASE}/api/v2/datacatalog?${params.toString()}`
  const response = await fetch(url, { credentials: 'include' })
  return handleResponse(response)
}

export async function createJob(payload) {
  const response = await fetch(`${API_BASE}/api/v1/jobs`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'include',
    body: JSON.stringify(payload)
  })
  return handleResponse(response)
}

export async function fetchJob(jobId) {
  const response = await fetch(`${API_BASE}/api/v1/jobs/${jobId}`, { credentials: 'include' })
  return handleResponse(response)
}

export async function fetchBriefReport(jobId) {
  const response = await fetch(`${API_BASE}/api/v2/reports/brief/${jobId}`, { credentials: 'include' })
  return handleResponse(response)
}

export async function fetchDetailedReport(jobId) {
  const response = await fetch(`${API_BASE}/api/v2/reports/detailed/${jobId}`, { credentials: 'include' })
  return handleResponse(response)
}

export async function fetchTrainingDefaults() {
  const response = await fetch(`${API_BASE}/api/v1/config/training-defaults`, { credentials: 'include' })
  return handleResponse(response)
}

export async function fetchModels() {
  const response = await fetch(`${API_BASE}/api/v1/models`, { credentials: 'include' })
  return handleResponse(response)
}

export async function fetchModelDetail(modelId) {
  const response = await fetch(`${API_BASE}/api/v1/models/${modelId}`, { credentials: 'include' })
  return handleResponse(response)
}

export async function fetchPredictionReport(jobId) {
  const response = await fetch(`${API_BASE}/api/v2/predictions/${jobId}`, { credentials: 'include' })
  return handleResponse(response)
}

export async function fetchBacktestReport(jobId) {
  const response = await fetch(`${API_BASE}/api/v2/reports/backtest/${jobId}`, { credentials: 'include' })
  return handleResponse(response)
}

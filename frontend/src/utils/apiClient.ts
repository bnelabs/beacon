/**
 * The single HTTP client for the BEACON SPA.
 *
 * Four hooks and the global search each carried their own copy of
 * "fetch and throw on non-2xx" (three byte-identical, two near-copies).
 * Drift between those copies is how silent-empty-category bugs survived:
 * a wrong URL used to parse a 404 body as a successful empty result.
 * One client, one error contract, one normaliser for the list-envelope
 * inconsistency across endpoints.
 *
 * This module is also the TypeScript seed: new frontend code should be
 * `.ts` and import from here (see docs/VERSIONING-and-language plan in
 * docs/LANGUAGE_STRATEGY.md).
 */

/** Configured API origin; empty means same-origin (nginx proxies /api/). */
export const API_ORIGIN: string =
  ((import.meta as unknown as { env?: Record<string, string> }).env?.VITE_API_BASE_URL ?? '') as string

export const API_BASE = `${API_ORIGIN}/api`

export interface ApiRequestOptions extends Omit<RequestInit, 'body'> {
  body?: BodyInit | null
  headers?: Record<string, string>
}

/**
 * Fetch an endpoint under `/api` and decode JSON.
 * Throws an `Error` with a human-readable message on any non-2xx status —
 * callers must never see a 404 body parsed as data. A 204 (or empty body)
 * resolves to `null` rather than throwing on `response.json()`.
 */
export const API_TOKEN_KEY = 'beacon.api_token'

function authHeaders(extra?: Record<string, string>): Record<string, string> {
  const headers: Record<string, string> = { 'Content-Type': 'application/json', ...extra }
  try {
    const token = window.localStorage.getItem(API_TOKEN_KEY)
    if (token) headers.Authorization = `Bearer ${token}`
  } catch {
    // storage unavailable: run without a token
  }
  return headers
}

export async function fetchApi<T = unknown>(
  endpoint: string,
  options: ApiRequestOptions = {}
): Promise<T | null> {
  const response = await fetch(`${API_BASE}${endpoint}`, {
    headers: authHeaders(options.headers),
    ...options
  })

  if (response.status === 401) {
    // The deployment requires a bearer token (BEACON_API_TOKEN). Surface it
    // once per episode so the app can ask, instead of sprinkling 401s.
    window.dispatchEvent(new CustomEvent('beacon:unauthorized'))
  }

  if (!response.ok) {
    const errorPayload = await response
      .json()
      .catch(() => ({ detail: 'Request failed' }))
    const detail = (errorPayload as { detail?: unknown })?.detail
    let message: string

    if (typeof detail === 'string') {
      message = detail
    } else if (detail && typeof detail === 'object' && 'user_friendly' in detail) {
      message = String((detail as { user_friendly: unknown }).user_friendly)
    } else if (detail && typeof detail === 'object' && 'technical' in detail) {
      message = String((detail as { technical: unknown }).technical)
    } else if (detail) {
      try {
        message = JSON.stringify(detail)
      } catch {
        message = 'Request failed'
      }
    } else {
      message = `HTTP ${response.status}`
    }

    throw new Error(message)
  }

  if (response.status === 204) {
    return null
  }

  const body = await response.text()
  return (body ? JSON.parse(body) : null) as T | null
}

/**
 * Fetch a fully-qualified URL (used where the path is built with query
 * strings outside `/api` conventions). Same throw-on-non-2xx contract.
 */
export async function fetchJson<T = unknown>(url: string): Promise<T> {
  const res = await fetch(url)
  if (!res.ok) {
    throw new Error(`${url} returned HTTP ${res.status}`)
  }
  return (await res.json()) as T
}

/**
 * Normalise the list-envelope inconsistency across endpoints:
 * `/v1/jobs`, `/models` and `/v1/catalogue` answer with a bare array while
 * `/v1/countries/` wraps rows in a `countries` key. Anything else is treated
 * as "no results" rather than throwing inside a render.
 */
export function asList<T = unknown>(data: unknown, key?: string): T[] {
  if (Array.isArray(data)) return data as T[]
  if (data && key && Array.isArray((data as Record<string, unknown>)[key])) {
    return (data as Record<string, unknown[]>)[key] as T[]
  }
  return []
}

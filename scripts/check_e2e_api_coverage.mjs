#!/usr/bin/env node
/**
 * Every API endpoint the frontend calls must be answered by the e2e mock.
 *
 * The defect this catches, which has now happened twice:
 *
 *   1. `/api/v1/notifications` and `/stats` were unmocked. Recorded in
 *      apiMocks.js: "because the default GET fallback used to answer 200 with an
 *      empty object the omission was invisible."
 *   2. `/api/v1/data-sources/disclosure` was unmocked. The fallback had been
 *      fixed to 404 by then, so it *was* visible -- as a console error, which the
 *      spec turns into a test failure. But it surfaced at whatever assertion the
 *      test happened to be executing when TanStack Query retried the failed
 *      query, which was a create-source form that had in fact submitted
 *      successfully (201). Diagnosing that needed the trace's network log.
 *
 * Making unknown paths 404 was the right fix and it is kept. What was missing is
 * a check that runs before a browser does: an endpoint the frontend adopts and
 * the mock does not cover should fail here, with the endpoint named, not twenty
 * minutes later in an unrelated Playwright assertion.
 *
 * It works by running the real handler rather than by grepping for strings, so
 * it cannot be fooled by a path that appears in a comment or a mock that matches
 * a different method. The handler is extracted from apiMocks.js by locating the
 * `page.route('**\/api\/**', ...)` call and taking its balanced body; apiMocks.js
 * is left untouched, because turning its handler into an export would mean
 * threading a fake `route` through the module for the benefit of a test.
 *
 * Usage:  node scripts/check_e2e_api_coverage.mjs [--json]
 * Exit 0 when every endpoint is handled, 1 with the unhandled list.
 */

import { readdirSync, readFileSync, statSync } from 'node:fs'
import { dirname, join, relative } from 'node:path'
import { fileURLToPath } from 'node:url'

const ROOT = dirname(dirname(fileURLToPath(import.meta.url)))
const MOCKS = join(ROOT, 'frontend', 'tests', 'apiMocks.js')
const SRC = join(ROOT, 'frontend', 'src')

/** Endpoints the e2e suite deliberately does not exercise, with the reason. */
const DECLARED_UNMOCKED = {
  // An entry here is a decision, not a silence, in the style of the disposition
  // census in backend/tests/test_reachability.py: the endpoint, and why no e2e
  // path reaches it. If a spec later navigates to the page that uses one, this
  // check fails and the right response is to mock it and delete the
  // declaration, not to widen the declaration.
  //
  // This list is deliberately EMPTY: every endpoint the frontend declares is
  // answered by the mock. The three entries that used to live here were
  // retired by following exactly the rule above -- the validation report got
  // a mock (with the real route's validated/not_validated branch logic) and a
  // spec walk-through via the #/results?jobId=104 deep link, and the two
  // analytics endpoints stopped being declared when their caller-less hooks
  // (useRiskScoreDistribution, useModelPerformanceComparison) were deleted as
  // dead code. An endpoint nothing calls does not need a declaration; it
  // needs a decision about whether a screen should exist for it.
}

// ---------------------------------------------------------------------------
// Collect the endpoints the frontend calls
// ---------------------------------------------------------------------------

function listDir(dir) {
  const out = []
  for (const name of readdirSync(dir)) {
    const full = join(dir, name)
    if (statSync(full).isDirectory()) out.push(...listDir(full))
    else out.push(full)
  }
  return out
}

/**
 * `/v1/jobs/${jobId}?x=${y}` -> `/api/v1/jobs/{param}`.
 *
 * Three forms appear in the source and all three have to survive:
 *   `/v1/jobs/${jobId}`                  an interpolated path segment
 *   `/v1/catalogue${buildQueryString(f)}` a whole query string appended wholesale
 *   `/v1/notifications${q ? `?${q}` : ''}` a nested template holding the query
 * The last two are query suffixes rather than path segments, so the query is cut
 * at the first `?` *after* interpolation, and anything still containing a `${`
 * is a nested template that can only be a query builder.
 */
function normalizeEndpoint(raw) {
  let path = ''
  let rest = raw
  // Walk the literal, replacing an interpolation with `{param}` only when it
  // occupies a path segment (i.e. it directly follows a `/`). An interpolation
  // anywhere else is a suffix -- a whole query string appended wholesale -- so
  // the path ends there.
  for (;;) {
    const at = rest.indexOf('${')
    if (at < 0) { path += rest; break }
    const close = rest.indexOf('}', at)
    if (close < 0) { path += rest.slice(0, at); break }
    path += rest.slice(0, at)
    rest = rest.slice(close + 1)
    if (path.endsWith('/')) {
      // A path segment: `/v1/jobs/${jobId}` -> `/v1/jobs/{param}`, and the rest
      // (`/data-quality`) is still path, so keep walking.
      path += '{param}'
      continue
    }
    // Not a path segment, so the interpolation is a suffix -- a whole query
    // string appended wholesale (`/v1/catalogue${buildQueryString(f)}`) or a
    // nested template holding one. Either way the path ends here.
    break
  }
  const queryAt = path.indexOf('?')
  if (queryAt >= 0) path = path.slice(0, queryAt)
  if (!path.startsWith('/')) return null
  return '/api' + path.replace(/\/$/, '')
}

function collectCalls() {
  const found = new Map() // endpoint -> { methods:Set, files:Set }
  for (const file of listDir(SRC)) {
    if (!/\.(js|jsx|ts|tsx)$/.test(file)) continue
    const text = readFileSync(file, 'utf-8')
    const re = /fetchApi\s*(?:<[^>]*>)?\s*\(\s*('([^']*)'|`([^`]*)`)/g
    let match
    while ((match = re.exec(text)) !== null) {
      const raw = match[2] ?? match[3]
      if (!raw || !raw.startsWith('/')) continue
      const endpoint = normalizeEndpoint(raw)
      if (!endpoint) continue
      // The method is a `method:` inside *this* call. The window stops at the
      // next `fetchApi(`, or a following call's options are attributed to this
      // one -- which is how a GET-only endpoint was reported as POST, because
      // `useCreateDataSource` happens to live below `useDataDisclosure` in the
      // same file.
      const tail = text
        .slice(match.index + match[0].indexOf('(') + 1, match.index + 400)
        .split('fetchApi')[0]
      const methodMatch = tail.match(/method:\s*['"`](\w+)['"`]/)
      const method = (methodMatch ? methodMatch[1] : 'GET').toUpperCase()
      const entry = found.get(endpoint) ?? {
        methods: new Set(),
        files: new Set()
      }
      entry.methods.add(method)
      entry.files.add(relative(ROOT, file))
      found.set(endpoint, entry)
    }
  }
  return found
}

// ---------------------------------------------------------------------------
// Extract and run the real mock handler
// ---------------------------------------------------------------------------

function balancedBody(source, startIndex) {
  let depth = 0
  let quote = null
  for (let i = startIndex; i < source.length; i += 1) {
    const ch = source[i]
    if (quote) {
      if (ch === '\\') { i += 1; continue }
      if (ch === quote) quote = null
      continue
    }
    if (ch === "'" || ch === '"' || ch === '`') { quote = ch; continue }
    if (ch === '(' || ch === '{' || ch === '[') depth += 1
    else if (ch === ')' || ch === '}' || ch === ']') {
      depth -= 1
      if (depth === 0) return source.slice(startIndex, i + 1)
    }
  }
  throw new Error('could not find the end of the route handler')
}

function extractHandler(source) {
  const marker = "page.route('**/api/**'"
  const at = source.indexOf(marker)
  if (at < 0) throw new Error(`${marker} not found in apiMocks.js`)
  const arrow = source.indexOf('=>', at)
  if (arrow < 0) throw new Error('route handler is not an arrow function')
  const bodyStart = source.indexOf('{', arrow)
  return balancedBody(source, bodyStart)
}

/** Build the module scope the handler body needs, then return an invoker. */
async function makeInvoker() {
  const source = readFileSync(MOCKS, 'utf-8')
  const body = extractHandler(source)
  // The data section is everything before the first function declaration: the
  // fixtures the handler closes over. It used to end at a named function
  // (registerBasemapTileMocks) that the basemap removal deleted; slicing to a
  // missing marker is slice(0, -1) -- the whole module, export keywords
  // included -- which new Function then rejects with "Unexpected token
  // 'export'". Anchoring on the first declaration cannot dangle like that.
  const firstFunction = source.match(/^async function /m)
  if (!firstFunction || firstFunction.index === undefined) {
    throw new Error('no function declaration found in apiMocks.js')
  }
  const dataSection = source.slice(0, firstFunction.index)

  // The data constants are module-scope in apiMocks.js; the handler closes over
  // them. Evaluate both in one scope rather than exporting anything.
  const factory = new Function(
    `${dataSection}\n
     return async function handle(request) {
       let fulfilled = null
       const route = {
         request: () => request,
         fulfill: (response) => { fulfilled = response; return undefined },
         continue: () => { fulfilled = { continued: true }; return undefined },
         abort: () => { fulfilled = { aborted: true }; return undefined }
       }
       const handler = async (route) => ${body}
       await handler(route)
       return fulfilled
     }`
  )
  return factory()
}

function requestFor(method, endpoint) {
  // A concrete id stands in for `{param}`; every matcher in the mock is a
  // `\\d+` or a literal, so 1 is representative. Query strings are dropped
  // because the handler normalises on pathname.
  const path = endpoint.replace(/\{param\}/g, '1')
  return {
    method: () => method,
    url: () => `http://127.0.0.1:8173${path}`
  }
}

function isFallback404(fulfilled) {
  if (!fulfilled || fulfilled.status !== 404) return false
  try {
    return JSON.parse(fulfilled.body).detail === 'Not Found'
  } catch {
    return false
  }
}

// ---------------------------------------------------------------------------

async function main() {
  const asJson = process.argv.includes('--json')
  const calls = collectCalls()
  const handle = await makeInvoker()

  const unhandled = []
  const handled = []
  for (const [endpoint, info] of [...calls.entries()].sort()) {
    for (const method of [...info.methods].sort()) {
      const result = await handle(requestFor(method, endpoint))
      const ok = result && !isFallback404(result) && !result.aborted
      const record = {
        method,
        endpoint,
        status: result?.status ?? null,
        files: [...info.files]
      }
      if (ok) handled.push(record)
      else unhandled.push(record)
    }
  }

  const undeclared = unhandled.filter(
    (record) => !(record.endpoint in DECLARED_UNMOCKED)
  )
  const staleDeclarations = Object.keys(DECLARED_UNMOCKED).filter(
    (endpoint) => !unhandled.some((record) => record.endpoint === endpoint)
  )

  if (asJson) {
    process.stdout.write(
      JSON.stringify({ handled, unhandled, staleDeclarations }, null, 2) + '\n'
    )
  } else {
    console.log(`frontend endpoints checked: ${handled.length + unhandled.length}`)
    console.log(`  answered by the e2e mock: ${handled.length}`)
    console.log(`  not answered:             ${unhandled.length}`)
    for (const record of unhandled) {
      const declared = record.endpoint in DECLARED_UNMOCKED
      console.log(
        `    ${record.method.padEnd(6)} ${record.endpoint.padEnd(52)} ` +
          `${declared ? 'declared' : 'UNDECLARED'}  ${record.files.join(', ')}`
      )
    }
    if (staleDeclarations.length) {
      console.log('  declared-but-now-handled (remove the declaration):')
      for (const endpoint of staleDeclarations) console.log(`    ${endpoint}`)
    }
  }

  if (undeclared.length || staleDeclarations.length) {
    if (!asJson) {
      console.error(
        '\nEvery endpoint the frontend calls must be answered by frontend/tests/apiMocks.js,\n' +
          'or listed in DECLARED_UNMOCKED above with the reason no e2e path reaches it.\n' +
          'An unmocked endpoint 404s, the spec fails on any console error, and the failure\n' +
          'is reported at an unrelated assertion -- which is how the missing\n' +
          '/api/v1/data-sources/disclosure mock presented as a create-source form that\n' +
          'would not close.'
      )
    }
    return 1
  }
  return 0
}

process.exit(await main())

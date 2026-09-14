# Frontend

The BEACON single-page application: its pages, state model, data fetching, and
the interactive features (search, onboarding, notifications, the risk map).

This document replaces three overlapping write-ups that were removed —
`IMPLEMENTATION_SUMMARY.md`, `REAL_TIME_JOBS_DOCUMENTATION.md` and
`docs/priority_3_features.md`. Those described the app as it was in late 2025 and
had drifted: they documented a Three.js 3D globe that no longer exists, an
`src/lib/utils/` path that had moved, notification priorities and categories that
the schema does not define, and a WebSocket feature that was never finished.
Everything below was read back off the code.

**What is not here:** component-level prop documentation. Read the components;
they are short and typed by convention.

## Stack

| Concern | Choice |
|---|---|
| UI | React 18.3, no TypeScript (`.jsx` throughout) |
| Build | Vite 7.1, esbuild minify, `target: es2020` |
| Maps | Deck.gl 9 (`@deck.gl/react`, `layers`, `geo-layers`, `aggregation-layers`) |
| Server state | TanStack Query 5 |
| Client state | Zustand 5 |
| Styling | Tailwind CSS 3.4 on the `bne-*` field-report token system (see [Design system](#design-system-and-brand)) |
| Tours | driver.js 1.3 (theme overridden in `styles/onboarding.css`) |
| E2E | Playwright 1.49 (see [`.github/workflows/README.md`](../.github/workflows/README.md)) |

There is **no** router library. Navigation is a Zustand store, not URL routing —
see below.

## Design system and brand

Reference screenshots live in `images/` (dashboard, risk map, analytics).

The interface is a **supervisory field report**: warm paper, ink type, hairline
rules. It deliberately avoids the idioms that make dashboards read as
generated — no blue, no dark chrome, no gradients, no glassmorphism, no emoji,
no pill-everything. Depth comes from borders; emphasis comes from typography.

### Principles

1. **Paper, not chrome.** Surfaces are warm off-whites; the only dark fills
   are ink overlays and pine buttons.
2. **Rules, not shadows.** Panels are defined by hairline borders; shadows are
   1–2 px and barely present.
3. **Typography carries hierarchy.** Serif display for mastheads and figures
   of record; tracked micro labels for eyebrows, table heads and badges;
   monospace tabular figures wherever numbers align in columns.
4. **Absence is visible.** An unmeasured value renders as an em-dash or a
   quiet dashed badge (`uncalibrated`), never as zero and never as a
   confident colour.
5. **One risk vocabulary.** The same four-band scale (plus *uncalibrated*)
   appears in badges, map markers, arcs, the heat ramp and the legend.

### Tokens (`tailwind.config.js`)

| Token family | Values | Role |
|---|---|---|
| `bne-paper`, `-dim`, `-raise` | `#F6F2E9`, `#ECE5D4`, `#FBF8F0` | App background, recessed wells, raised strips |
| `bne-card` | `#FCFAF4` | Panel surface |
| `bne-line`, `-soft`, `-strong` | `#E2DAC8`, `#EBE5D6`, `#CFC3A9` | Hairline borders and dividers |
| `bne-ink`, `-soft`, `bne-muted`, `bne-faint` | `#26211A` … `#948A72` | Text hierarchy |
| `bne-chalk` | `#FBF8F1` | Warm white text on saturated fills |
| `bne-pine` | `#2C5545` (+50/100/600/700) | Brand: active nav, primary buttons, links |
| `bne-moss` / `bne-ochre` / `bne-rust` / `bne-clay` | `#55703B` / `#A87C1D` / `#BE5F2E` / `#A33D22` | Risk & status scale: low → moderate → high → critical |
| `bne-stone` | `#8A8168` | Neutral / *uncalibrated* |

Every `bne-*` class referenced anywhere in `src/` must exist in the config.
Tailwind silently drops unknown utilities, which is how an earlier theme
shipped ~170 dead classes (`bne-frost`, `bne-indigo`, `bne-sky`,
`shadow-bne-card`) — borders and shadows that never rendered.

### Typography

- **Display**: Source Serif 4 (loaded from Google Fonts with Georgia /
  Palatino fallbacks, so the identity survives offline). Page mastheads,
  card titles, headline figures.
- **UI**: system sans stack (no webfont dependency for body text).
- **Data**: system monospace with `tabular-nums` (`.bne-figure`, `.tnum`).
- **Micro labels**: `.bne-micro` — 10.5 px, uppercase, 0.09 em tracking;
  the signature device for section eyebrows, table heads and badges.

### Components

- `ui/Card` — hairline panel; optional `accent` prop draws a 2 px top rule in
  a risk tone so a panel's severity is legible before its numbers.
- `ui/Badge` — printed label: 3 px radius, uppercase micro type, tint on
  hairline. `riskVariant(level)` (exported from the module) is the single
  level→variant map; it knows `uncalibrated` (dashed, quiet) and renders
  unknown levels neutrally.
- `ui/Button` — flat fills and hairline outlines; primary is pine,
  destructive clay. No gradient or glow states.
- `ui/PageContainer` — breadcrumb, micro eyebrow, serif title over a hairline
  rule; the masthead of every page.
- The sidebar footer renders the build version from `__APP_VERSION__`
  (stamped by Vite from `package.json`, which `scripts/release.py` keeps in
  step with the repository `VERSION` file) — no more hard-coded "v3".
- `Brand.jsx` — the beacon mark (signal tower, ochre lamp, pine broadcast
  arcs) drawn on the same 24-unit grid and 1.6 stroke as the navigation
  icons; `Wordmark` sets BEACON over *Banking Early-Alert Network*. The mark
  is also `public/favicon.svg`.
- Icons elsewhere are monogram chips (search results, plugin lists): two
  letters in a hairline square, never emoji.

### Resilience and honesty in the shell

- `components/ErrorBoundary.jsx` wraps the routed page (keyed per page). A
  view that throws degrades to a quiet clay panel inside working chrome with
  retry/reload; before it, one malformed payload blanked the entire app.
- The dashboard's System Status card reads `GET /api/v1/system/status`
  (30 s poll) and renders measured CPU/memory/disk/GPU meters. An
  unreachable backend shows an *Unreachable* badge — never green.
- Metric cards render `—` for absent measurements (e.g. completeness when
  the payload omits it); no card invents a delta ("vs last week" style).

### Risk map palette

`data/network-connections.js` exports `RISK_COLORS`
(low `#67854F`, medium `#C29A33`, high `#C05F2C`, critical `#8A3320`,
uncalibrated `#8A8168`) on the CARTO **light** basemap. Region fills are warm
washes, labels are ink with paper halos, and the heatmap ramp runs
moss → ochre → rust → clay. `MapLegend` documents the bands, the heat ramp
and the *uncalibrated* state.

## Pages and navigation

`frontend/src/store/useRouter.js` holds `currentPage` and `params`; `App.jsx`
switches on `currentPage` to render a lazily-imported page. Because this is not
URL-based routing, **deep links do not survive a reload** — the app always opens
on `dashboard`.

| `currentPage` | Component | Notes |
|---|---|---|
| `dashboard` | `pages/Dashboard.jsx` | Eagerly loaded; welcome banner, live system-status meters, serif stat cards |
| `globe` | `pages/RiskMapPage.jsx` | Route key is still `globe`; the page is the **Risk Map** |
| `models` | `pages/Models.jsx` | |
| `jobs` | `pages/Jobs.jsx` | Batch mode, WebSocket hook |
| `results` | `pages/Results.jsx` | Breadcrumb child of `jobs` |
| `datasources` | `pages/DataSources.jsx` | |
| `countries` | `pages/CountryProfiles.jsx` | World Bank sync, CSV/JSON export |
| `performance` | `pages/ModelPerformance.jsx` | |
| `data-quality` | `pages/DataQuality.jsx` | |
| `analytics` | `pages/Analytics.jsx` | |
| `settings` | `pages/Settings.jsx` | Restart the onboarding tour |
| `help` | `pages/Help.jsx` | |

`components/Breadcrumbs.jsx` derives a trail from a static parent map.
`performance`, `data-quality` and `analytics` are absent from that map, so those
three pages render no breadcrumb.

## Data fetching

- The base URL comes from `import.meta.env.VITE_API_BASE_URL` (default empty,
  meaning same-origin). In Docker, nginx serves the SPA and proxies `/api/` to
  the backend, so the default is correct there. See [`deployment.md`](deployment.md).
- Each domain has a hook under `frontend/src/hooks/`: `useApi` (jobs, models,
  batch cancel), `useCountries`, `useNotifications`, `useDataQuality`,
  `useAnalytics`, `useJobsWebSocket`, `useOnboarding`.
- Polling intervals are set per query rather than globally: notifications
  every 30 s, data-quality `stats` and `sources` every 60 s, `trends` every
  120 s.

## Global search (⌘K / Ctrl+K)

`components/GlobalSearch.jsx` opens on ⌘K and searches a merged list, navigable
with ↑/↓ and Enter. Result icons are two-letter monogram chips in hairline
squares — the emoji set they replaced rendered differently on every platform
and read as decoration, not information. It merges nine static *Page* entries with four live
categories: Jobs, Models, Data Catalogue and Countries.

The live endpoints are **inconsistent about their envelope**, so the component
normalises rather than assumes: `/api/v1/jobs`, `/api/models` and
`/api/v1/catalogue` answer with a bare array, while `/api/v1/countries/` wraps
its rows in a `countries` key. `asList(data, key)` accepts either.

Responses are read through a small `fetchJson` helper that **throws on a non-2xx
status**. That is deliberate: these queries previously called `res.json()`
unconditionally, and a 404 body of `{"detail": "Not Found"}` parses perfectly
well, so a wrong URL produced a silently empty category instead of an error.

That is exactly what had happened — all four categories were once broken, in two
different ways, and none of it was visible:

| Category | Was | Now |
|---|---|---|
| Jobs | read `jobsData.jobs` off a bare array | `asList(jobsData, 'jobs')` |
| Models | read `modelsData.models`, and `id`/`model_name`/`version` instead of `model_id`/`name`/`model_version` | `asList(modelsData, 'models')` with the real field names |
| Data Catalogue | fetched `/api/v1/data-catalogue/`, which does not exist | `/api/v1/catalogue` |

Only *Countries* had matched the component's assumption. The e2e mocks had been
written to match the broken caller — one served `/api/v1/data-catalogue` with
`{items: [...]}`, and the mock's default fallback answered **200 with `{}`** for
any unknown path, so a wrong URL looked like a successful empty result. Both are
corrected: the mocks now mirror the real API and unknown paths 404, and
`full-frontend.spec.js` asserts that a search for a job, a model and a catalogue
item actually returns each one.

## Onboarding tour

`hooks/useOnboarding.js` drives a seven-step driver.js tour: Welcome, Risk Map,
Models, Jobs, Results, Global Search, Done. Completion is persisted to
localStorage; `Settings` exposes "Restart Tour". Targets are marked with
`data-tour` attributes (`Header.jsx` for the search button, `Sidebar.jsx` for
nav items), so adding a step means adding the attribute as well as the step.

## Risk map

The former 3D globe is gone. `pages/RiskMapPage.jsx` renders a 2D Deck.gl map via
`components/map/RiskMap.jsx` and `MapLegend.jsx` (the legend documents the
bands, the heat ramp and the *uncalibrated* state):

- a free CARTO **light** raster basemap — **no Mapbox token required** — so the
  map sits on the same paper idiom as the rest of the shell
- `ScatterplotLayer` for banks/regions coloured by `RISK_COLORS`
- `HeatmapLayer` for liquidity intensity on a moss→ochre→rust→clay ramp
- `ArcLayer` for interbank exposures (unscored edges draw in stone, never in a
  colour that would assert a risk level the data does not carry)
- `GeoJsonLayer` for warm region washes and `TextLayer` labels in ink with
  paper halos

`three`, `@react-three/fiber`, `@react-three/drei` and the entire
`src/components/globe/` directory were removed. The route key stays `globe` so
existing navigation keeps working, but all user-facing copy says "Risk Map"
and the component file is now `RiskMapPage.jsx`.
`src/data/network-connections.js` still holds the static connection set.

## Jobs: real-time updates and batch operations

**Batch cancel works.** `POST /api/v1/jobs/batch/cancel` accepts up to 50 job
ids, cancels only jobs in `pending` or `running`, and returns partial success
with a per-job reason (`BatchCancelResponse`: `cancelled`, `failed`,
`total_requested`, `total_cancelled`). The Jobs page drives it through
`useBatchCancelJobs()` with a multi-select mode.

**Real-time updates work, over Redis.** The socket lives in the API process but
most progress is written by the Celery worker, so the delivery is routed through
Redis rather than done in-process — `JobService.update_job_status` publishes, and
a relay task in the API lifespan fans out to connected clients. The full
protocol and the reasoning are in the WebSocket section of [`api.md`](api.md).

The client dials **same-origin** (`${protocol}//${window.location.host}/api/v1/jobs/ws`),
which nginx proxies. Two earlier defects are worth remembering because neither
produced an error: the server had no publisher at all (`broadcast_job_update`
was exported but called from nowhere), and the hook hard-coded port `8000`, which
nothing listens on — the backend is on 3456 and reached through the proxy on 9876.

Two further details are easy to reintroduce:

- `isConnected` is React **state**, not a read of `wsRef` during render. A ref
  mutation does not re-render, so the earlier version could never light up the
  "Live updates active" badge even with the socket open.
- The `onUpdate`/`onError` callbacks are held in refs. The Jobs page passes an
  inline arrow, which changes identity every render; without the refs, `connect`
  would change identity too and the socket would be torn down and re-established
  in a loop.

If the socket cannot stay up, the hook retries five times and then polls
`['jobs']` every 5 seconds, so the page keeps refreshing. Polling stops as soon as
a socket opens.

## Notifications

`components/NotificationBell.jsx` sits in the header and polls
`/api/v1/notifications` every 30 s. It shows an unread badge, a dropdown panel,
relative timestamps, and a "mark all read" action; clicking an item marks it
read and follows its `action_url`.

The accepted values are defined by `backend/schemas/notification.py` — types
`info | success | warning | error | alert`, priorities
`low | medium | high | critical`, categories `model | data | job | system |
risk`. See [`api.md`](api.md#notifications) for the response fields.

## Country profiles

`pages/CountryProfiles.jsx` lists World Bank indicators with search and
region/risk filters, can trigger a sync (`POST /api/v1/countries/sync`), and
exports via `src/utils/export.js` (`downloadCSV`, `downloadJSON`,
`formatCountriesForExport`). Note the path: the removed implementation summary
recorded this as `src/lib/utils/export.js`, which no longer exists.

## Model performance and data quality dashboards

`pages/ModelPerformance.jsx` summarises model counts, mean R²/RMSE, a health
breakdown (ready / training / stale / failed) and a sortable comparison table,
backed by the model catalogue endpoints.

`pages/DataQuality.jsx` shows overall health, a freshness distribution, anomaly
counts and a 14-day trend chart, backed by `/api/v1/data-quality/{stats,sources,trends}`.
The composite quality score and the freshness thresholds are defined in
[`api.md`](api.md#data-quality-score).

## Build and code splitting

`vite.config.js` splits three vendor chunks — `react-vendor`, `query-vendor` and
`onboarding` — and every page except `Dashboard` is loaded with `React.lazy()`.

The `three-vendor` chunk recorded in the removed implementation summary is gone
along with Three.js, and so are the specific bundle-size figures from that
document: they measured a build that no longer exists. Re-measure with
`npm run build` if you need current numbers rather than trusting a stale table.

## Running it

```bash
cd frontend
npm install
npm run dev      # http://localhost:5173, expects the API on :3456
npm run build    # production bundle into dist/
npx playwright test
```

Container build and deployment are covered in [`deployment.md`](deployment.md).

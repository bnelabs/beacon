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
| Styling | Tailwind CSS 3.4 with a custom `bne-*` palette |
| Tours | driver.js 1.3 |
| E2E | Playwright 1.49 (see [`.github/workflows/README.md`](../.github/workflows/README.md)) |

There is **no** router library. Navigation is a Zustand store, not URL routing —
see below.

## Pages and navigation

`frontend/src/store/useRouter.js` holds `currentPage` and `params`; `App.jsx`
switches on `currentPage` to render a lazily-imported page. Because this is not
URL-based routing, **deep links do not survive a reload** — the app always opens
on `dashboard`.

| `currentPage` | Component | Notes |
|---|---|---|
| `dashboard` | `pages/Dashboard.jsx` | Eagerly loaded; hosts the welcome banner |
| `globe` | `pages/GlobeView.jsx` | Route key is still `globe`; the page is the **Risk Map** |
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
with ↑/↓ and Enter.

**Only two of its four live categories actually return results.** The static
*Page* entries (nine of them) and *Countries* work. The other three are broken
by two separate mismatches with the API:

| Category | What the component does | Reality |
|---|---|---|
| Jobs | reads `jobsData.jobs` from `/api/v1/jobs/` | that endpoint returns a bare **array** (`List[JobResponse]`), so `.jobs` is `undefined` |
| Models | reads `modelsData.models` from `/api/v1/models/` | likewise a bare **array** (`List[ModelSummary]`) |
| Data Catalogue | fetches `/api/v1/data-catalogue/` | that route does not exist — it is `/api/v1/catalogue/` (a **404**) |

None of the three checks `res.ok`, so all three fail silently and the search
simply shows fewer categories than it claims. Only *Countries* matches the
component's assumption, because `CountryListResponse` really is an object with a
`countries` key.

## Onboarding tour

`hooks/useOnboarding.js` drives a seven-step driver.js tour: Welcome, Risk Map,
Models, Jobs, Results, Global Search, Done. Completion is persisted to
localStorage; `Settings` exposes "Restart Tour". Targets are marked with
`data-tour` attributes (`Header.jsx` for the search button, `Sidebar.jsx` for
nav items), so adding a step means adding the attribute as well as the step.

## Risk map

The former 3D globe is gone. `pages/GlobeView.jsx` renders a 2D Deck.gl map via
`components/map/RiskMap.jsx` and `MapLegend.jsx`:

- a free CARTO raster basemap — **no Mapbox token required**
- `ScatterplotLayer` for banks/regions coloured by risk
- `HeatmapLayer` for liquidity intensity
- `ArcLayer` for interbank exposures
- `GeoJsonLayer` for boundaries and `TextLayer` for labels

`three`, `@react-three/fiber`, `@react-three/drei` and the entire
`src/components/globe/` directory were removed. The route key stays `globe` so
existing navigation keeps working, but all user-facing copy says "Risk Map".
`src/data/network-connections.js` still holds the static connection set.

## Jobs: real-time updates and batch operations

**Batch cancel works.** `POST /api/v1/jobs/batch/cancel` accepts up to 50 job
ids, cancels only jobs in `pending` or `running`, and returns partial success
with a per-job reason (`BatchCancelResponse`: `cancelled`, `failed`,
`total_requested`, `total_cancelled`). The Jobs page drives it through
`useBatchCancelJobs()` with a multi-select mode.

**Real-time updates do not.** The Jobs page calls `useJobsWebSocket`, but
neither half is connected:

1. The server never broadcasts. `broadcast_job_update()` exists in
   `backend/api/routes/jobs_ws.py` and is listed in `__all__`, but nothing calls
   it, so no `job_update` frame is ever sent.
2. The client dials the wrong port. The hook builds
   `ws://${window.location.hostname}:8000/api/v1/jobs/ws`, but the backend is
   published on **3456** and nginx proxies `/api/` from **9876**. Nothing
   listens on 8000 in the Docker deployment.

The handshake and heartbeats are implemented and would work — see the
WebSocket section of [`api.md`](api.md) for the protocol. What is missing is a
caller for the broadcaster and a same-origin URL.

The user-visible consequence is mild, which is why this went unnoticed: after
five failed reconnects the hook falls back to invalidating `['jobs']` every
5 seconds, so the page does refresh. It refreshes by polling, not by push. The
green "Live updates active" badge never appears — `isConnected` is read from a
ref during render, and nothing triggers a re-render when the socket opens.

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

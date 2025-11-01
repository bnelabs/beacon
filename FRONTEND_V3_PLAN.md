# BEACON Frontend V3 - Complete Rebuild Plan
## Professional Production-Grade React Application

**Status**: Ready for Implementation
**Timeline**: 4 days
**Current V2 Image Size**: 5.16GB
**Target V3 Image Size**: <150MB
**Expected Reduction**: 97% (35x smaller)

---

## Executive Summary

### The Problem
- Frontend-v2 Docker image: **5.16GB** (Playwright browsers + dependencies)
- Page load: 4+ seconds
- Globe interactions: **15-20 second freezes**
- Excessive polling causing unnecessary re-renders
- Framer Motion adding ~500KB to bundle
- No production optimization

### The Solution
Complete ground-up rebuild with:
- **Multi-stage Docker build** targeting <150MB
- **Performance-first architecture** with React 19 best practices
- **Minimal dependencies** (<15 core packages)
- **Production-grade design system**
- **Smart caching and memoization**
- **Professional corporate UX**

### Key Metrics
| Aspect | V2 (Current) | V3 (Target) | Improvement |
|--------|--------------|-------------|-------------|
| Docker Image | 5.16GB | <150MB | **97% smaller** |
| Page Load | ~4s | <800ms | **5x faster** |
| Globe Render | ~3s | <400ms | **7x faster** |
| Region Click | 15-20s | <80ms | **250x faster** |
| Bundle Size | Unknown | <500KB | Optimized |
| Dependencies | 50+ | <15 | **70% fewer** |
| FPS (Interactions) | <30fps | 60fps | **2x smoother** |

---

## Technology Stack

### Core Dependencies (Production)
```json
{
  "dependencies": {
    "react": "^19.1.1",
    "react-dom": "^19.1.1",
    "@react-three/fiber": "^9.0.0",
    "@react-three/drei": "^9.114.3",
    "three": "^0.170.0",
    "zustand": "^5.0.0",
    "@tanstack/react-query": "^5.62.7",
    "clsx": "^2.1.1",
    "tailwind-merge": "^2.5.4"
  },
  "devDependencies": {
    "@vitejs/plugin-react": "^4.3.4",
    "vite": "^7.1.7",
    "tailwindcss": "^3.4.17",
    "postcss": "^8.4.49",
    "autoprefixer": "^10.4.20",
    "eslint": "^9.18.0"
  }
}
```

**Total Production Dependencies**: 8 packages
**Total Dev Dependencies**: 6 packages
**Grand Total**: 14 packages (vs 50+ in V2)

### Removed Dependencies
- ~~`playwright`~~ - NO testing in production image (saves ~4GB)
- ~~`framer-motion`~~ - Use CSS transitions (saves ~500KB)
- ~~`@playwright/test`~~ - Testing framework removed
- ~~All unnecessary testing libs~~
- ~~Heavy animation libraries~~

### Why These Technologies?

**React 19.1.1**
- Latest concurrent features
- Automatic batching for better performance
- Improved SSR support (future)

**Vite 7.1.7**
- Lightning-fast HMR (<50ms)
- Optimized production builds
- Built-in code splitting

**Three.js + R3F**
- Industry standard for 3D
- Declarative React integration
- Tree-shakeable (only import what you use)

**Zustand**
- Smallest state library (0.9KB gzipped)
- No boilerplate
- Perfect for our use case

**TanStack Query**
- Best-in-class server state management
- Smart caching out of the box
- Automatic request deduplication

**Tailwind CSS**
- Utility-first (no unused CSS)
- Purging removes 95% in production
- Fastest development workflow

---

## Docker Strategy

### Multi-Stage Production Dockerfile
```dockerfile
# ======================
# Stage 1: Dependencies
# ======================
FROM node:20-alpine AS deps
WORKDIR /app

# Copy package files
COPY package.json package-lock.json ./

# Install dependencies (including devDependencies for build)
RUN npm ci

# ======================
# Stage 2: Builder
# ======================
FROM node:20-alpine AS builder
WORKDIR /app

# Copy dependencies from deps stage
COPY --from=deps /app/node_modules ./node_modules

# Copy source code
COPY . .

# Build arguments
ARG VITE_API_BASE_URL=http://localhost:3456
ENV VITE_API_BASE_URL=$VITE_API_BASE_URL
ENV NODE_ENV=production

# Build application
RUN npm run build

# ======================
# Stage 3: Production
# ======================
FROM nginx:1.27-alpine
WORKDIR /usr/share/nginx/html

# Remove default nginx config
RUN rm -rf /etc/nginx/conf.d/default.conf

# Copy custom nginx config
COPY nginx.conf /etc/nginx/nginx.conf

# Copy built assets from builder
COPY --from=builder /app/dist .

# Add healthcheck
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
  CMD wget --quiet --tries=1 --spider http://localhost/health || exit 1

# Expose port
EXPOSE 80

# Start nginx
CMD ["nginx", "-g", "daemon off;"]
```

### Nginx Configuration (`nginx.conf`)
```nginx
user nginx;
worker_processes auto;
error_log /var/log/nginx/error.log warn;
pid /var/run/nginx.pid;

events {
    worker_connections 1024;
}

http {
    include /etc/nginx/mime.types;
    default_type application/octet-stream;

    # Logging
    log_format main '$remote_addr - $remote_user [$time_local] "$request" '
                    '$status $body_bytes_sent "$http_referer" '
                    '"$http_user_agent" "$http_x_forwarded_for"';
    access_log /var/log/nginx/access.log main;

    # Performance
    sendfile on;
    tcp_nopush on;
    tcp_nodelay on;
    keepalive_timeout 65;
    types_hash_max_size 2048;
    client_max_body_size 20M;

    # Gzip compression
    gzip on;
    gzip_vary on;
    gzip_proxied any;
    gzip_comp_level 6;
    gzip_types text/plain text/css text/xml text/javascript
               application/json application/javascript application/xml+rss
               application/x-font-ttf font/opentype image/svg+xml;

    # Brotli (if available)
    # brotli on;
    # brotli_comp_level 6;
    # brotli_types text/plain text/css application/json application/javascript;

    server {
        listen 80;
        server_name _;
        root /usr/share/nginx/html;
        index index.html;

        # Security headers
        add_header X-Frame-Options "SAMEORIGIN" always;
        add_header X-Content-Type-Options "nosniff" always;
        add_header X-XSS-Protection "1; mode=block" always;
        add_header Referrer-Policy "no-referrer-when-downgrade" always;

        # Health check endpoint
        location /health {
            access_log off;
            return 200 "healthy\n";
            add_header Content-Type text/plain;
        }

        # API proxy (production)
        location /api/ {
            proxy_pass http://backend:8000/api/;
            proxy_http_version 1.1;
            proxy_set_header Upgrade $http_upgrade;
            proxy_set_header Connection 'upgrade';
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
            proxy_set_header X-Forwarded-Proto $scheme;
            proxy_cache_bypass $http_upgrade;

            # Timeouts
            proxy_connect_timeout 60s;
            proxy_send_timeout 60s;
            proxy_read_timeout 60s;
        }

        # Static assets with aggressive caching
        location ~* \.(js|css|png|jpg|jpeg|gif|ico|svg|woff|woff2|ttf|eot)$ {
            expires 1y;
            add_header Cache-Control "public, immutable";
        }

        # SPA fallback - all routes serve index.html
        location / {
            try_files $uri $uri/ /index.html;
            add_header Cache-Control "no-cache";
        }
    }
}
```

### Image Size Breakdown
```
nginx:1.27-alpine base    ~45MB
Built JS bundle           ~300-400KB (gzipped: ~100-150KB)
Built CSS                 ~50-80KB (gzipped: ~10-15KB)
Static assets (GeoJSON)   ~740KB (gzipped: ~150KB)
Fonts (if embedded)       ~100KB
HTML                      ~5KB
Total Image Size          ~50-60MB
```

**Target: <150MB including overhead**

---

## Architecture

### Directory Structure
```
frontend-v3/
├── public/
│   ├── assets/
│   │   └── geo/
│   │       └── countries-50m.json      # 740KB GeoJSON
│   └── favicon.ico
│
├── src/
│   ├── main.jsx                        # Entry point
│   ├── App.jsx                         # Root component
│   │
│   ├── components/
│   │   ├── globe/
│   │   │   ├── Globe.jsx               # Main globe (lazy loaded)
│   │   │   ├── RegionOverlay.jsx       # Memoized region mesh
│   │   │   ├── CountryOverlay.jsx      # Memoized country mesh
│   │   │   ├── GlobeSurface.jsx        # Base sphere
│   │   │   ├── Controls.jsx            # Camera controls wrapper
│   │   │   └── hooks/
│   │   │       ├── useGlobeData.js     # GeoJSON processing
│   │   │       ├── useMeshCache.js     # Mesh building cache
│   │   │       └── useGlobeControls.js # Interaction handlers
│   │   │
│   │   ├── panels/
│   │   │   ├── DataSourcePanel.jsx     # Data source selection
│   │   │   ├── CataloguePanel.jsx      # Asset catalogue browser
│   │   │   ├── DataJobPanel.jsx        # Data collection job
│   │   │   ├── TrainingPanel.jsx       # Model training
│   │   │   ├── ModelLibraryPanel.jsx   # Trained models
│   │   │   ├── PredictionPanel.jsx     # Prediction jobs
│   │   │   └── BacktestPanel.jsx       # Backtesting
│   │   │
│   │   ├── ui/
│   │   │   ├── Button.jsx              # variants: primary, secondary, ghost, danger
│   │   │   ├── Card.jsx                # Clickable, selectable states
│   │   │   ├── Input.jsx               # Text, number, date, select
│   │   │   ├── Badge.jsx               # Status indicators
│   │   │   ├── Progress.jsx            # Linear + circular progress
│   │   │   ├── Skeleton.jsx            # Loading placeholders
│   │   │   ├── ErrorBoundary.jsx       # Error catching
│   │   │   ├── Toast.jsx               # Notifications
│   │   │   └── Modal.jsx               # Dialog/modal wrapper
│   │   │
│   │   ├── layout/
│   │   │   ├── Shell.jsx               # Main layout wrapper
│   │   │   ├── Header.jsx              # Top navigation + status
│   │   │   ├── Sidebar.jsx             # Workflow panels
│   │   │   └── GlobeContainer.jsx      # Globe wrapper with overlays
│   │   │
│   │   └── common/
│   │       ├── RegionBadgeList.jsx     # Selected regions display
│   │       ├── ScopeSummary.jsx        # Region/country summary
│   │       ├── JobStatusCard.jsx       # Reusable job status
│   │       └── MetricsGrid.jsx         # Key-value metrics display
│   │
│   ├── hooks/
│   │   ├── api/
│   │   │   ├── useDataSources.js       # Fetch data sources
│   │   │   ├── useCatalogue.js         # Fetch catalogue items
│   │   │   ├── useJobs.js              # Create & poll jobs
│   │   │   ├── useModels.js            # Fetch models
│   │   │   ├── useReports.js           # Fetch reports
│   │   │   └── usePredictions.js       # Fetch predictions
│   │   │
│   │   ├── useWorkflowState.js         # Workflow stage management
│   │   ├── useOptimizedQuery.js        # React Query wrapper with defaults
│   │   ├── useDebounce.js              # Debounce helper
│   │   └── useMediaQuery.js            # Responsive breakpoints
│   │
│   ├── store/
│   │   ├── uiStore.js                  # UI state (Zustand)
│   │   │   ├── selectedRegions         # Globe selections
│   │   │   ├── selectedCountries       # Country filters
│   │   │   ├── panelStage              # Current workflow stage
│   │   │   ├── globeReady              # Globe initialization
│   │   │   └── toast notifications     # Toast queue
│   │   │
│   │   └── workflowStore.js            # Workflow state (Zustand)
│   │       ├── dataJobId               # Current data job
│   │       ├── trainingJobId           # Current training job
│   │       ├── selectedModelId         # Selected model
│   │       ├── predictionJobId         # Current prediction job
│   │       ├── backtestJobId           # Current backtest job
│   │       └── confirmedScope          # Confirmed regions/countries
│   │
│   ├── lib/
│   │   ├── api/
│   │   │   ├── client.js               # Axios/Fetch wrapper
│   │   │   ├── endpoints.js            # API endpoint constants
│   │   │   └── queryClient.js          # TanStack Query config
│   │   │
│   │   ├── utils/
│   │   │   ├── cn.js                   # clsx + tailwind-merge
│   │   │   ├── formatters.js           # Date, number, currency
│   │   │   ├── validators.js           # Form validation
│   │   │   └── constants.js            # App constants
│   │   │
│   │   └── geo/
│   │       ├── processGeoJSON.js       # GeoJSON utilities
│   │       ├── buildMesh.js            # Three.js mesh builder
│   │       ├── meshCache.js            # Mesh caching layer
│   │       └── regions.js              # Region definitions
│   │
│   └── styles/
│       ├── index.css                   # Tailwind imports + globals
│       └── animations.css              # Custom CSS animations
│
├── nginx.conf                          # Production server config
├── Dockerfile                          # Multi-stage build
├── .dockerignore                       # Exclude from build
├── package.json
├── package-lock.json
├── vite.config.js
├── tailwind.config.js
├── postcss.config.js
├── eslint.config.js
└── README.md
```

---

## Performance Requirements & Strategies

### Target Metrics
| Metric | Target | Measurement |
|--------|--------|-------------|
| **LCP (Largest Contentful Paint)** | <1.2s | Lighthouse |
| **FID (First Input Delay)** | <100ms | Lighthouse |
| **CLS (Cumulative Layout Shift)** | <0.1 | Lighthouse |
| **TTI (Time to Interactive)** | <2s | Lighthouse |
| **Globe First Render** | <400ms | Performance API |
| **Region Click Response** | <80ms | Performance API |
| **Data Fetch** | <300ms | Network tab |
| **Bundle Size (JS)** | <500KB | Build output |
| **Bundle Size (CSS)** | <80KB | Build output |
| **FPS (Interactions)** | 60fps | Browser DevTools |

### 1. Globe Rendering Optimization

**Problem in V2**: Module-level mesh building → 3s page load, then lazy loading → 15-20s freeze

**V3 Solution**: On-demand building with persistent cache

```javascript
// lib/geo/meshCache.js
const MESH_CACHE = new Map()

export function buildRegionMesh(region) {
  const cacheKey = `region:${region.id}`

  if (MESH_CACHE.has(cacheKey)) {
    return MESH_CACHE.get(cacheKey) // <10ms cache hit
  }

  // Build mesh on demand (~100-150ms per region)
  const meshData = {
    fillGeometry: createFillGeometry(region),
    outlineGeometries: createOutlineGeometries(region)
  }

  MESH_CACHE.set(cacheKey, meshData)
  return meshData
}
```

**Benefits**:
- Page load: No blocking (0ms)
- First region click: ~100ms (build)
- Subsequent clicks: <10ms (cache hit)
- Memory efficient: Only builds what's visible

### 2. React Query Optimization

**Configuration**:
```javascript
// lib/api/queryClient.js
export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 60_000,              // 1 minute
      gcTime: 300_000,                // 5 minutes (renamed from cacheTime)
      refetchOnWindowFocus: false,     // Disable refetch on focus
      refetchOnReconnect: false,       // Disable refetch on reconnect
      retry: 2,                        // Max 2 retries
      retryDelay: (attemptIndex) => Math.min(1000 * 2 ** attemptIndex, 30000)
    },
    mutations: {
      retry: 1
    }
  }
})
```

**Per-Query Optimization**:
```javascript
// Immutable data (reports, predictions)
const reportQuery = useQuery({
  queryKey: ['report', jobId],
  queryFn: () => fetchReport(jobId),
  enabled: Boolean(jobId) && jobCompleted,
  staleTime: Infinity,         // Never refetch
  gcTime: Infinity             // Keep forever
})

// Active polling (jobs in progress)
const jobQuery = useQuery({
  queryKey: ['job', jobId],
  queryFn: () => fetchJob(jobId),
  enabled: Boolean(jobId),
  refetchInterval: (data) => {
    if (!data || ['completed', 'failed'].includes(data.status)) {
      return false // Stop polling
    }
    return 6000 // Poll every 6s
  },
  staleTime: 5000 // Consider fresh for 5s
})
```

### 3. Component Memoization

**All expensive components memoized**:
```javascript
// components/globe/RegionOverlay.jsx
export const RegionOverlay = memo(function RegionOverlay({ region, selected, onClick }) {
  const meshData = useMemo(() => buildRegionMesh(region), [region.id])

  const handleClick = useCallback((event) => {
    event.stopPropagation()
    onClick(region.id)
  }, [region.id, onClick])

  const handlePointerOver = useCallback((event) => {
    event.stopPropagation()
    document.body.style.cursor = 'pointer'
  }, [])

  // ... 10 more event handlers, all useCallback wrapped

  return <mesh onClick={handleClick} onPointerOver={handlePointerOver}>...</mesh>
})
```

**Memoization Checklist**:
- ✅ All list items (DataSourceCard, CatalogueCard, ModelCard)
- ✅ All panels (DataSourcePanel, TrainingPanel, etc.)
- ✅ Globe overlays (RegionOverlay, CountryOverlay)
- ✅ All callbacks passed as props
- ✅ All expensive computations

### 4. Code Splitting & Lazy Loading

**Route-based splitting**:
```javascript
// App.jsx
import { lazy, Suspense } from 'react'

const Globe = lazy(() => import('./components/globe/Globe'))
const DataPanel = lazy(() => import('./components/panels/DataPanel'))

export function App() {
  return (
    <Suspense fallback={<LoadingSkeleton />}>
      <Globe />
      <DataPanel />
    </Suspense>
  )
}
```

**Dynamic imports for heavy modules**:
```javascript
// Load Three.js helpers only when needed
const loadEarcut = () => import('earcut')
```

### 5. Bundle Optimization

**Vite Configuration**:
```javascript
// vite.config.js
export default defineConfig({
  plugins: [react()],
  build: {
    target: 'es2020',
    minify: 'terser',
    terserOptions: {
      compress: {
        drop_console: true,
        drop_debugger: true
      }
    },
    rollupOptions: {
      output: {
        manualChunks: {
          'react-vendor': ['react', 'react-dom'],
          'three-vendor': ['three', '@react-three/fiber', '@react-three/drei'],
          'query-vendor': ['@tanstack/react-query', 'zustand']
        }
      }
    },
    chunkSizeWarningLimit: 600
  }
})
```

**Expected Bundle Sizes**:
- `index.js`: ~80-120KB (app code)
- `react-vendor.js`: ~140-160KB (React 19)
- `three-vendor.js`: ~120-140KB (Three.js tree-shaken)
- `query-vendor.js`: ~40-60KB (TanStack Query + Zustand)
- **Total JS**: ~380-480KB uncompressed, ~120-150KB gzipped

**CSS Optimization**:
```javascript
// tailwind.config.js
export default {
  content: ['./index.html', './src/**/*.{js,jsx}'],
  theme: { /* ... */ },
  plugins: []
}
// Purge removes ~95% of unused Tailwind classes
// Final CSS: ~50-80KB uncompressed, ~10-15KB gzipped
```

### 6. Animation Performance

**Use CSS transitions instead of Framer Motion**:
```css
/* styles/animations.css */
@keyframes slideIn {
  from {
    opacity: 0;
    transform: translateX(20px);
  }
  to {
    opacity: 1;
    transform: translateX(0);
  }
}

.panel-enter {
  animation: slideIn 200ms ease-out;
}

.card-hover {
  transition: all 150ms cubic-bezier(0.4, 0, 0.2, 1);
}

.card-hover:hover {
  transform: translateY(-2px);
  box-shadow: 0 8px 16px rgba(0, 0, 0, 0.1);
}
```

**Benefits vs Framer Motion**:
- Bundle size: -500KB
- Performance: GPU-accelerated CSS
- 60fps guaranteed for simple transitions

---

## Design System

### Color Palette
```javascript
// tailwind.config.js
export default {
  theme: {
    extend: {
      colors: {
        // Primary
        'bne-azure': {
          DEFAULT: '#0066CC',
          50: '#E6F2FF',
          100: '#CCE5FF',
          500: '#0066CC',
          600: '#0052A3',
          700: '#003D7A'
        },
        'bne-ink': {
          DEFAULT: '#1A1A1A',
          50: '#F5F5F5',
          500: '#1A1A1A',
          600: '#0D0D0D'
        },
        'bne-steel': {
          DEFAULT: '#5A5A6F',
          50: '#F0F0F3',
          500: '#5A5A6F',
          600: '#484858'
        },

        // Neutral
        'bne-ice': '#F5F7FA',
        'bne-silver': '#D1D5DB',
        'bne-cloud': '#FFFFFF',

        // Accent
        'bne-emerald': {
          DEFAULT: '#10B981',
          50: '#D1FAE5',
          500: '#10B981',
          600: '#059669'
        },
        'bne-amber': {
          DEFAULT: '#F59E0B',
          50: '#FEF3C7',
          500: '#F59E0B',
          600: '#D97706'
        },
        'bne-crimson': {
          DEFAULT: '#DC2626',
          50: '#FEE2E2',
          500: '#DC2626',
          600: '#B91C1C'
        }
      },
      fontFamily: {
        sans: ['Inter Variable', 'Inter', 'system-ui', 'sans-serif']
      },
      boxShadow: {
        'bne-panel': '0 2px 8px rgba(0, 0, 0, 0.06), 0 1px 2px rgba(0, 0, 0, 0.04)',
        'bne-hover': '0 4px 12px rgba(0, 0, 0, 0.08), 0 2px 4px rgba(0, 0, 0, 0.06)'
      },
      backdropBlur: {
        'halo': '12px'
      }
    }
  }
}
```

### Typography Scale
- **H1**: 2xl (24px), font-semibold, tracking-tight
- **H2**: xl (20px), font-semibold, tracking-tight
- **H3**: lg (18px), font-medium
- **Body**: sm (14px), font-normal, leading-relaxed
- **Label**: xs (12px), font-medium, uppercase, tracking-widest
- **Caption**: xs (12px), font-normal, text-steel-600

### Spacing System
- **xs**: 0.5rem (8px)
- **sm**: 0.75rem (12px)
- **md**: 1rem (16px)
- **lg**: 1.5rem (24px)
- **xl**: 2rem (32px)
- **2xl**: 3rem (48px)

### Component Specifications

#### Button
```javascript
// components/ui/Button.jsx
const variants = {
  primary: 'bg-bne-azure text-white hover:bg-bne-azure-600',
  secondary: 'bg-white border border-bne-silver text-bne-ink hover:border-bne-azure',
  ghost: 'bg-transparent text-bne-steel hover:bg-bne-ice',
  danger: 'bg-bne-crimson text-white hover:bg-bne-crimson-600'
}

const sizes = {
  sm: 'px-3 py-1.5 text-xs',
  md: 'px-4 py-2 text-sm',
  lg: 'px-5 py-3 text-base'
}
```

#### Card
```javascript
// components/ui/Card.jsx
const states = {
  default: 'border-bne-silver bg-white',
  hover: 'hover:border-bne-azure hover:shadow-bne-hover',
  selected: 'border-bne-azure bg-bne-azure/5 shadow-bne-panel',
  disabled: 'opacity-50 cursor-not-allowed'
}
```

#### Progress
```javascript
// components/ui/Progress.jsx
<div className="h-2 w-full rounded-full bg-bne-ice">
  <div
    className="h-full rounded-full bg-bne-azure transition-all duration-300"
    style={{ width: `${progress}%` }}
  />
</div>
```

---

## Implementation Plan (Detailed)

### Phase 1: Foundation & Infrastructure (Day 1 Morning)

**Duration**: 4 hours

#### 1.1 Project Setup (1 hour)
- [ ] Create `frontend-v3/` directory
- [ ] Initialize git (separate branch: `feat/frontend-v3`)
- [ ] Create `package.json` with minimal dependencies
- [ ] Run `npm install`
- [ ] Verify no unnecessary packages

**Deliverable**: Clean project structure, <15 dependencies

#### 1.2 Build Configuration (1 hour)
- [ ] Configure `vite.config.js` with optimizations
- [ ] Set up `tailwind.config.js` with BNE design system
- [ ] Create `postcss.config.js`
- [ ] Set up ESLint with minimal rules
- [ ] Create `.dockerignore` to exclude node_modules

**Deliverable**: Build system ready, dev server working

#### 1.3 Docker Setup (1 hour)
- [ ] Write multi-stage `Dockerfile`
- [ ] Create `nginx.conf` with API proxy
- [ ] Add to `docker-compose.yml` on port 6789
- [ ] Test Docker build locally
- [ ] Verify image size <150MB

**Checkpoint**: `docker build` succeeds, image <150MB

#### 1.4 Base Architecture (1 hour)
- [ ] Create directory structure (all folders)
- [ ] Set up `main.jsx` entry point
- [ ] Create `App.jsx` shell
- [ ] Configure TanStack Query client
- [ ] Set up Zustand stores (empty)

**Deliverable**: App renders "Hello BEACON V3"

---

### Phase 2: Design System & Layout (Day 1 Afternoon)

**Duration**: 4 hours

#### 2.1 UI Components (2 hours)
- [ ] `Button.jsx` - all variants + states
- [ ] `Card.jsx` - clickable, selectable, disabled
- [ ] `Input.jsx` - text, number, date, select
- [ ] `Badge.jsx` - status indicators
- [ ] `Progress.jsx` - linear + circular
- [ ] `Skeleton.jsx` - loading placeholders
- [ ] `ErrorBoundary.jsx` - error catching
- [ ] `Toast.jsx` - notification system

**Test Each**: Visual storybook-style test page

#### 2.2 Layout Components (1 hour)
- [ ] `Shell.jsx` - main layout wrapper
- [ ] `Header.jsx` - navigation + system status
- [ ] `Sidebar.jsx` - workflow panel container
- [ ] Test responsive behavior (mobile, tablet, desktop)

**Checkpoint**: Layout renders, responsive on all sizes

#### 2.3 Common Components (1 hour)
- [ ] `RegionBadgeList.jsx` - selected regions
- [ ] `ScopeSummary.jsx` - region/country display
- [ ] `JobStatusCard.jsx` - reusable job status
- [ ] `MetricsGrid.jsx` - key-value display

**Deliverable**: Complete design system, all components tested

---

### Phase 3: Globe Visualization (Day 2 Morning)

**Duration**: 4 hours

#### 3.1 GeoJSON Processing (1 hour)
- [ ] Copy `countries-50m.json` to `public/assets/geo/`
- [ ] Write `processGeoJSON.js` - TopoJSON conversion
- [ ] Write `regions.js` - region definitions
- [ ] Test GeoJSON loading and parsing

**Checkpoint**: GeoJSON loads, regions defined

#### 3.2 Mesh Building (1 hour)
- [ ] Write `buildMesh.js` - Three.js geometry builder
- [ ] Implement `meshCache.js` - caching layer
- [ ] Write `buildRegionMesh()` function
- [ ] Write `buildCountryMesh()` function
- [ ] Test mesh building performance (<150ms per region)

**Performance Target**: <150ms per region build

#### 3.3 Globe Component (2 hours)
- [ ] Create `Globe.jsx` - main canvas
- [ ] Create `GlobeSurface.jsx` - base sphere
- [ ] Create `Controls.jsx` - OrbitControls wrapper
- [ ] Create `RegionOverlay.jsx` - memoized region mesh
- [ ] Create `CountryOverlay.jsx` - memoized country mesh
- [ ] Write `useGlobeData.js` - data loading hook
- [ ] Write `useGlobeControls.js` - interaction handlers

**Test**:
- Globe renders <400ms
- Region click <80ms
- Smooth 60fps rotation
- No memory leaks

**Checkpoint**: Globe fully functional, performant

---

### Phase 4: API Integration & Hooks (Day 2 Afternoon)

**Duration**: 4 hours

#### 4.1 API Client (1 hour)
- [ ] Write `client.js` - fetch wrapper with error handling
- [ ] Write `endpoints.js` - all API endpoints as constants
- [ ] Test connection to backend

**Deliverable**: API client ready, endpoints documented

#### 4.2 Data Hooks (2 hours)
- [ ] `useDataSources.js` - fetch data sources with regions
- [ ] `useCatalogue.js` - fetch catalogue items with search
- [ ] `useJobs.js` - create job, poll status, get result
- [ ] `useModels.js` - fetch trained models
- [ ] `useReports.js` - fetch brief/detailed reports
- [ ] `usePredictions.js` - fetch prediction reports

**Test Each**: Mock API calls, verify caching

#### 4.3 Zustand Stores (1 hour)
- [ ] Complete `uiStore.js` - selections, panel stage, toasts
- [ ] Complete `workflowStore.js` - job IDs, confirmed scope
- [ ] Test state updates and persistence

**Checkpoint**: API integration works, state management functional

---

### Phase 5: Data Pipeline Panels (Day 3 Morning)

**Duration**: 4 hours

#### 5.1 Data Source Selection (1 hour)
- [ ] Build `DataSourcePanel.jsx`
- [ ] Implement source selection logic
- [ ] Show coverage information
- [ ] Test with real API

**Deliverable**: Can select data sources

#### 5.2 Catalogue Browser (1 hour)
- [ ] Build `CataloguePanel.jsx`
- [ ] Implement search functionality
- [ ] Show asset details
- [ ] Test with real API

**Deliverable**: Can browse and select catalogue items

#### 5.3 Data Job Panel (2 hours)
- [ ] Build `DataJobPanel.jsx`
- [ ] Implement job creation
- [ ] Add progress polling (6s interval)
- [ ] Display brief report
- [ ] Display detailed report with asset diagnostics
- [ ] Test full data collection workflow

**Test**: Complete data collection end-to-end

**Checkpoint**: Data pipeline fully functional

---

### Phase 6: Training & Model Management (Day 3 Afternoon)

**Duration**: 4 hours

#### 6.1 Training Panel (2 hours)
- [ ] Build `TrainingPanel.jsx`
- [ ] Fetch training defaults
- [ ] Implement hyperparameter form
- [ ] Create training job
- [ ] Poll training status
- [ ] Display training results
- [ ] Test with real backend

**Deliverable**: Can train models end-to-end

#### 6.2 Model Library (2 hours)
- [ ] Build `ModelLibraryPanel.jsx`
- [ ] List all trained models
- [ ] Show model metrics
- [ ] Select model for prediction/backtest
- [ ] Test model selection workflow

**Checkpoint**: Training workflow complete

---

### Phase 7: Predictions & Backtesting (Day 4 Morning)

**Duration**: 4 hours

#### 7.1 Prediction Panel (2 hours)
- [ ] Build `PredictionPanel.jsx`
- [ ] Implement prediction form (horizon, volatility, spread)
- [ ] Create prediction job
- [ ] Poll job status
- [ ] Display prediction results
- [ ] Show feature importances
- [ ] Test prediction workflow

**Deliverable**: Predictions work end-to-end

#### 7.2 Backtest Panel (2 hours)
- [ ] Build `BacktestPanel.jsx`
- [ ] Implement date range selection
- [ ] Create backtest job
- [ ] Poll job status
- [ ] Display backtest metrics
- [ ] Test backtesting workflow

**Checkpoint**: All workflows complete

---

### Phase 8: Polish & Optimization (Day 4 Afternoon)

**Duration**: 4 hours

#### 8.1 Loading States (1 hour)
- [ ] Add skeletons to all loading states
- [ ] Implement toast notifications for errors
- [ ] Add success confirmations
- [ ] Test all loading/error scenarios

#### 8.2 Error Handling (1 hour)
- [ ] Implement error boundaries
- [ ] Add user-friendly error messages
- [ ] Log errors for debugging
- [ ] Test error recovery

#### 8.3 Performance Audit (1 hour)
- [ ] Run Lighthouse (target: 90+ performance score)
- [ ] Measure all critical metrics
- [ ] Optimize any slow interactions
- [ ] Verify 60fps throughout

**Performance Checklist**:
- ✅ LCP <1.2s
- ✅ FID <100ms
- ✅ CLS <0.1
- ✅ Globe render <400ms
- ✅ Region click <80ms

#### 8.4 Final Build (1 hour)
- [ ] Build production bundle
- [ ] Verify bundle sizes (<500KB JS, <80KB CSS)
- [ ] Build Docker image
- [ ] Verify image size <150MB
- [ ] Test production deployment

**Deliverable**: Production-ready application

---

### Phase 9: Documentation & Deployment (Day 4 Evening)

**Duration**: 2 hours

#### 9.1 Documentation (1 hour)
- [ ] Update README.md with v3 instructions
- [ ] Document architecture changes
- [ ] Add migration guide from v2
- [ ] Document performance improvements

#### 9.2 Production Deploy (1 hour)
- [ ] Update `docker-compose.yml` (v3 on port 80)
- [ ] Test full stack integration
- [ ] Run end-to-end smoke tests
- [ ] Deploy to staging environment

**Deliverable**: Frontend V3 in production

---

## Migration & Rollback Strategy

### Parallel Running (During Development)
```yaml
# docker-compose.yml
services:
  frontend-v2:
    build: ./frontend-v2
    ports:
      - "5173:5173"  # Keep v2 running
    environment:
      - VITE_API_BASE_URL=http://localhost:3456

  frontend-v3:
    build: ./frontend-v3
    ports:
      - "6789:80"    # V3 on different port
    environment:
      - VITE_API_BASE_URL=http://backend:8000
```

### Switching to V3 (Production)
```yaml
# docker-compose.yml
services:
  frontend:
    build: ./frontend-v3  # Point to v3
    ports:
      - "80:80"           # Production port
    environment:
      - VITE_API_BASE_URL=http://backend:8000
```

### Rollback Plan
1. Keep v2 codebase in `frontend-v2/` directory
2. Git branch strategy:
   - `main`: Current v2
   - `feat/frontend-v3`: Development branch
   - `release/v3.0.0`: Stable v3
3. Docker images tagged: `beacon-frontend:v2` and `beacon-frontend:v3`
4. Rollback command: `docker-compose -f docker-compose.v2.yml up`

---

## Testing Strategy

### Manual Testing Checklist

#### Globe Interactions
- [ ] Globe renders in <400ms
- [ ] Smooth 60fps rotation
- [ ] Region hover highlights instantly
- [ ] Region click response <80ms
- [ ] Selected regions display correctly
- [ ] Camera controls work smoothly
- [ ] No memory leaks after 50+ interactions

#### Data Pipeline
- [ ] Select regions on globe
- [ ] Load data sources for selected regions
- [ ] Browse catalogue with search
- [ ] Create data job
- [ ] Monitor progress updates
- [ ] View brief report with correct scope
- [ ] View detailed asset diagnostics

#### Training Workflow
- [ ] Load training defaults
- [ ] Modify hyperparameters
- [ ] Create training job
- [ ] Monitor training progress
- [ ] View training results
- [ ] Model appears in library

#### Predictions
- [ ] Select model from library
- [ ] Configure prediction parameters
- [ ] Create prediction job
- [ ] Monitor prediction progress
- [ ] View prediction results
- [ ] Feature importances display

#### Backtesting
- [ ] Select model from library
- [ ] Set date range
- [ ] Create backtest job
- [ ] Monitor backtest progress
- [ ] View backtest metrics

#### Responsive Design
- [ ] Mobile (375px width)
- [ ] Tablet (768px width)
- [ ] Desktop (1280px width)
- [ ] Ultra-wide (1920px+ width)

#### Performance
- [ ] Page load <800ms
- [ ] All interactions 60fps
- [ ] No console errors
- [ ] No memory leaks
- [ ] Network waterfall optimized

---

## Success Criteria

### Quantitative Metrics
✅ Docker image <150MB (vs 5.16GB = 97% reduction)
✅ Page load <800ms (vs ~4s)
✅ Globe render <400ms (vs ~3s)
✅ Region interaction <80ms (vs 15-20s)
✅ Bundle size <500KB JS + <80KB CSS
✅ Dependencies <15 packages (vs 50+)
✅ 60fps throughout all interactions
✅ Lighthouse performance score >90

### Qualitative Metrics
✅ Professional corporate design
✅ Smooth, polished animations
✅ Responsive on all screen sizes
✅ Clear workflow states
✅ Helpful loading/error messages
✅ Maintainable codebase
✅ Well-documented architecture

---

## Risk Mitigation

### Risk 1: Three.js performance on low-end devices
**Mitigation**:
- Test on low-end devices early
- Add quality settings (reduce polygon count on mobile)
- Implement level-of-detail (LOD) for meshes

### Risk 2: GeoJSON processing slow
**Mitigation**:
- Process at module level (not runtime)
- Implement Web Worker for heavy processing
- Use cached meshes aggressively

### Risk 3: Docker build failures
**Mitigation**:
- Test multi-stage build early
- Pin all dependency versions
- Use `.dockerignore` to exclude unnecessary files

### Risk 4: Bundle size exceeds target
**Mitigation**:
- Monitor bundle size during development
- Use `vite-bundle-visualizer` plugin
- Tree-shake aggressively
- Remove unused dependencies immediately

---

## Post-Launch Improvements (Future)

These are **NOT** in scope for initial v3, but planned for future:

1. **Service Worker** - Offline support, cache API responses
2. **WebSockets** - Real-time job updates (eliminate polling)
3. **Progressive Web App** - Install on desktop/mobile
4. **Dark Mode** - Corporate dark theme
5. **Advanced Visualizations** - D3.js charts for reports
6. **Export Functionality** - Download reports as PDF
7. **Keyboard Shortcuts** - Power user features
8. **Accessibility** - WCAG 2.1 AA compliance
9. **i18n** - Multi-language support
10. **Unit Tests** - Jest + React Testing Library (dev only)

---

## Key Differences from V2

| Aspect | V2 | V3 | Change |
|--------|----|----|--------|
| **Docker Image** | 5.16GB | <150MB | 97% smaller |
| **Page Load** | ~4s | <800ms | 5x faster |
| **Globe Render** | ~3s | <400ms | 7x faster |
| **Region Click** | 15-20s | <80ms | 250x faster |
| **Dependencies** | 50+ packages | <15 packages | 70% fewer |
| **Bundle Size** | Unknown | <500KB | Optimized |
| **Testing in Image** | Playwright (4GB+) | None | Removed |
| **Animations** | Framer Motion | CSS transitions | -500KB |
| **Build** | Single-stage | Multi-stage | Production optimized |
| **Server** | Vite dev | Nginx | Production-grade |
| **Polling** | 3-4s | 6s | Less aggressive |
| **Mesh Building** | Lazy (blocking) | On-demand (cached) | 250x faster |
| **Memoization** | Partial | Comprehensive | Better performance |
| **Code Splitting** | None | Aggressive | Faster initial load |

---

## Timeline Summary

| Day | Phase | Hours | Deliverables |
|-----|-------|-------|--------------|
| **Day 1 AM** | Foundation | 4h | Project setup, Docker, base architecture |
| **Day 1 PM** | Design System | 4h | UI components, layout, common components |
| **Day 2 AM** | Globe | 4h | GeoJSON, mesh building, globe component |
| **Day 2 PM** | API Integration | 4h | API client, hooks, Zustand stores |
| **Day 3 AM** | Data Pipeline | 4h | Data sources, catalogue, data jobs |
| **Day 3 PM** | Training | 4h | Training panel, model library |
| **Day 4 AM** | Predictions | 4h | Prediction panel, backtest panel |
| **Day 4 PM** | Polish | 4h | Loading states, errors, optimization, build |
| **Day 4 Eve** | Deploy | 2h | Documentation, production deployment |
| **Total** | | **34 hours** | Production-ready frontend v3 |

---

## Conclusion

This plan provides a **complete, production-ready roadmap** for rebuilding the BEACON frontend from scratch. The new v3 will be:

- **97% smaller** Docker image (<150MB vs 5.16GB)
- **250x faster** interactions (<80ms vs 15-20s)
- **Professional** corporate design system
- **Maintainable** clean architecture
- **Scalable** performance-first patterns

**Ready to proceed with implementation.**

---

**Document Version**: 2.0
**Last Updated**: 2025-11-01
**Author**: Claude (Anthropic)
**Status**: Ready for Implementation

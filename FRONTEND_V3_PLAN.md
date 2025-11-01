# BEACON Frontend V3 - Complete Rebuild Plan

**Goal**: Build a professional, smooth, responsive frontend with minimal Docker footprint and blazing-fast performance.

---

## Core Principles

1. **Lean & Fast**: Zero unnecessary dependencies, aggressive code splitting
2. **Professional UX**: Corporate-grade design system, smooth animations
3. **Performance First**: <100ms interactions, <1s page load, optimized React patterns
4. **Production Ready**: Multi-stage Docker build, <200MB image size
5. **Developer Experience**: Clean architecture, easy to maintain

---

## Technology Stack

### Core (Minimal Dependencies)
- **React 19.1.1** - Latest with concurrent features
- **Vite 7.1.7** - Lightning-fast build tool
- **Three.js 0.170.0** - Globe visualization only
- **@react-three/fiber 9.0.0** - React renderer for Three.js
- **@react-three/drei** - Essential Three.js helpers (camera controls, loaders)

### State Management
- **Zustand 5.0.0** - Lightweight global state (<1KB)
- **TanStack Query 5.x** - Server state with smart caching

### Styling
- **Tailwind CSS 3.4.x** - Utility-first CSS framework
- **Tailwind Merge** - Conditional class merging
- **PostCSS** - CSS processing only

### Build & Dev
- **Vite** - Dev server and bundler
- **ESLint** - Code quality (minimal config)
- **TypeScript** (optional) - Type safety without overhead

### **REMOVED**
- ~~Playwright~~ - **NO E2E testing in production image**
- ~~Framer Motion~~ - Use CSS transitions instead
- ~~Heavy animation libraries~~
- ~~Unnecessary testing frameworks~~

---

## Docker Strategy

### Multi-Stage Build
```dockerfile
# Stage 1: Build
FROM node:20-alpine AS builder
WORKDIR /app
COPY package*.json ./
RUN npm ci --only=production
COPY . .
RUN npm run build

# Stage 2: Production
FROM nginx:alpine
COPY --from=builder /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/nginx.conf
EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
```

### Target Image Size: <200MB
- Alpine Linux base: ~50MB
- Nginx: ~20MB
- Built assets: ~10-30MB
- **Total**: <100MB (vs current 5.16GB = 50x reduction!)

---

## Architecture

### Directory Structure
```
frontend-v3/
├── src/
│   ├── components/
│   │   ├── globe/
│   │   │   ├── Globe.jsx              # Main globe component
│   │   │   ├── RegionOverlay.jsx      # Memoized region meshes
│   │   │   ├── CountryOverlay.jsx     # Memoized country meshes
│   │   │   └── useGlobeData.js        # Hook for GeoJSON processing
│   │   ├── panels/
│   │   │   ├── DataPanel.jsx          # Data exploration
│   │   │   ├── ModelPanel.jsx         # Model management
│   │   │   ├── PredictionPanel.jsx    # Predictions
│   │   │   └── BacktestPanel.jsx      # Backtesting
│   │   ├── ui/
│   │   │   ├── Card.jsx               # Reusable card
│   │   │   ├── Button.jsx             # Button variants
│   │   │   ├── Input.jsx              # Form inputs
│   │   │   ├── Badge.jsx              # Status badges
│   │   │   └── Progress.jsx           # Progress indicators
│   │   └── layout/
│   │       ├── Shell.jsx              # Main layout
│   │       ├── Header.jsx             # Top navigation
│   │       └── Sidebar.jsx            # Side panels
│   ├── hooks/
│   │   ├── useDataSources.js          # Data fetching
│   │   ├── useModels.js               # Model queries
│   │   ├── useJobs.js                 # Job polling
│   │   └── useOptimizedQuery.js       # Smart React Query wrapper
│   ├── store/
│   │   ├── uiStore.js                 # UI state (Zustand)
│   │   └── workflowStore.js           # Workflow state
│   ├── utils/
│   │   ├── api.js                     # API client
│   │   ├── geoUtils.js                # GeoJSON processing
│   │   └── formatters.js              # Data formatters
│   ├── styles/
│   │   └── index.css                  # Tailwind imports
│   ├── App.jsx
│   └── main.jsx
├── public/
│   └── assets/
│       └── geo/
│           └── countries-50m.json     # GeoJSON data
├── nginx.conf                         # Production server config
├── Dockerfile                         # Multi-stage build
├── package.json
├── vite.config.js
├── tailwind.config.js
└── postcss.config.js
```

---

## Performance Requirements

### Critical Metrics
| Metric | Target | Current V2 |
|--------|--------|------------|
| **Page Load** | <1s | ~4s |
| **Globe Render** | <500ms | ~3s |
| **Region Click** | <100ms | 15-20s (!!) |
| **Data Fetch** | <300ms | Variable |
| **Poll Interval** | 6s | 3-4s |
| **Docker Image** | <200MB | 5.16GB |

### Optimization Strategies

1. **Globe Rendering**
   - On-demand mesh building with caching
   - React.memo on all overlays
   - useCallback for all event handlers
   - GeoJSON processing at module level (not runtime)
   - Progressive enhancement (load regions on demand)

2. **React Query Optimization**
   - `staleTime: Infinity` for immutable data (reports, predictions)
   - `staleTime: 5000ms` for polling queries
   - `refetchInterval: 6000ms` for active jobs
   - Disabled `refetchOnWindowFocus` globally
   - Smart query invalidation

3. **Component Memoization**
   - All list items wrapped in React.memo
   - All panels wrapped in React.memo
   - useCallback for all callbacks passed as props
   - useMemo for expensive computations

4. **Code Splitting**
   - Lazy load panel components
   - Lazy load globe on route change
   - Dynamic imports for heavy modules

5. **Bundle Optimization**
   - Tree shaking enabled
   - Minification + compression
   - CSS purging (Tailwind)
   - Asset optimization (images, fonts)

---

## Design System

### Color Palette (Corporate)
```js
colors: {
  // Primary
  'bne-azure': '#0066CC',      // Primary action color
  'bne-ink': '#1A1A1A',        // Primary text
  'bne-steel': '#5A5A6F',      // Secondary text

  // Neutral
  'bne-ice': '#F5F7FA',        // Background
  'bne-silver': '#D1D5DB',     // Borders
  'bne-cloud': '#FFFFFF',      // Panels

  // Accent
  'bne-emerald': '#10B981',    // Success
  'bne-amber': '#F59E0B',      // Warning
  'bne-crimson': '#DC2626',    // Error
}
```

### Typography
- **Font**: Inter Variable (from Google Fonts CDN)
- **Headings**: Font-weight 600, tracking tight
- **Body**: Font-weight 400, line-height relaxed
- **Labels**: Font-weight 500, uppercase, tracking wide

### Spacing & Layout
- **Container**: max-w-7xl (1280px)
- **Gap**: 4, 6, 8 (1rem, 1.5rem, 2rem)
- **Padding**: 4, 6, 8 for panels
- **Border Radius**: rounded-2xl (1rem) for panels, rounded-full for buttons

### Components
- **Panels**: White background with subtle shadow, rounded corners
- **Buttons**: Rounded-full, hover states, disabled states
- **Cards**: Hover effects, click feedback, selected states
- **Inputs**: Focus rings, validation states
- **Progress**: Smooth transitions, percentage display

---

## Implementation Phases

### Phase 1: Foundation (Day 1)
- [ ] Create frontend-v3 directory
- [ ] Set up Vite + React 19 + Tailwind
- [ ] Configure multi-stage Dockerfile
- [ ] Create lean nginx.conf
- [ ] Set up Zustand stores
- [ ] Configure TanStack Query with optimal defaults
- [ ] Build design system components (Button, Card, Input)

### Phase 2: Layout & Globe (Day 1-2)
- [ ] Build Shell/Header/Sidebar layout
- [ ] Port Globe component (clean rewrite)
- [ ] Implement on-demand mesh building
- [ ] Add caching layer for meshes
- [ ] Memoize all overlays
- [ ] Test globe performance (<500ms render)

### Phase 3: Data Pipeline (Day 2)
- [ ] Build DataPanel with workflow stages
- [ ] Implement datasource selection
- [ ] Build catalogue browser
- [ ] Add job creation & polling
- [ ] Display brief/detailed reports
- [ ] Test data fetch performance

### Phase 4: Training & Models (Day 3)
- [ ] Build training configuration panel
- [ ] Implement training job polling
- [ ] Create model library component
- [ ] Add model selection & details
- [ ] Test training workflow

### Phase 5: Predictions & Backtest (Day 3)
- [ ] Build prediction panel
- [ ] Implement prediction job creation
- [ ] Display prediction results
- [ ] Build backtest panel
- [ ] Add backtest results visualization

### Phase 6: Polish & Optimization (Day 4)
- [ ] Add loading states & skeletons
- [ ] Implement error boundaries
- [ ] Add toast notifications
- [ ] Optimize bundle size
- [ ] Test Docker image (<200MB)
- [ ] Performance audit (all metrics green)

### Phase 7: Production Deploy (Day 4)
- [ ] Build production image
- [ ] Update docker-compose.yml
- [ ] Test end-to-end workflow
- [ ] Update README with new architecture
- [ ] Document performance improvements

---

## Migration Strategy

### Parallel Development
1. Keep frontend-v2 running during v3 development
2. Use different ports (v2: 5173, v3: 6789)
3. Test v3 thoroughly before switching
4. Once v3 is stable, deprecate v2

### Data Compatibility
- Both v3 and v2 hit same backend API
- No backend changes required
- Test with existing data jobs

### Rollback Plan
- Keep v2 container in docker-compose
- Switch between v2/v3 with environment variable
- Document differences in README

---

## Success Criteria

### Performance
✅ Page load <1s
✅ Globe render <500ms
✅ Region interaction <100ms
✅ Docker image <200MB
✅ No blocking operations

### UX
✅ Smooth animations (60fps)
✅ Responsive on all screen sizes
✅ Professional design system
✅ Clear workflow states
✅ Helpful loading/error states

### Code Quality
✅ Clean component structure
✅ Proper memoization
✅ No prop drilling
✅ Typed where beneficial
✅ Well-documented

---

## Key Differences from V2

| Aspect | V2 | V3 |
|--------|----|----|
| **Docker Image** | 5.16GB | <200MB |
| **Dependencies** | 50+ packages | <20 packages |
| **Testing in Image** | Playwright included | Removed |
| **Page Load** | ~4s | <1s |
| **Region Click** | 15-20s | <100ms |
| **Mesh Building** | Lazy (slow) | On-demand cached (fast) |
| **Polling** | 3-4s | 6s |
| **Animations** | Framer Motion | CSS transitions |
| **Build Strategy** | Single stage | Multi-stage |
| **Server** | Vite dev | Nginx production |

---

## Next Steps

1. **Create frontend-v3 directory** - Fresh start
2. **Set up package.json** - Minimal dependencies
3. **Build Dockerfile** - Multi-stage Alpine build
4. **Create design system** - Reusable components
5. **Rebuild globe** - Performance-first architecture
6. **Port workflows** - Data → Training → Prediction
7. **Test & optimize** - Meet all performance criteria
8. **Deploy** - Replace v2 in docker-compose

---

**Target Completion**: 4 days
**Expected Image Size Reduction**: 50x (from 5.16GB to <200MB)
**Expected Performance Improvement**: 100-200x for interactions
**Code Cleanliness**: Enterprise-grade architecture
